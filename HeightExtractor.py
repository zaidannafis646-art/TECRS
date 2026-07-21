import math
from datetime import datetime, timedelta
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsProcessing,
    QgsFeatureSink,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterDateTime,
    QgsProcessingParameterNumber,
    QgsSpatialIndex,
    QgsGeometry,
    QgsPointXY,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsDistanceArea
)

class TecrsHeightExtractor(QgsProcessingAlgorithm):
    BUILDINGS = 'BUILDINGS'
    SHADOWS = 'SHADOWS'
    IMAGE_TIME = 'IMAGE_TIME'
    TZ_OFFSET = 'TZ_OFFSET'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(self.BUILDINGS, 'Building Footprints (Shapefile)', [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterFeatureSource(self.SHADOWS, 'Shadow Polygons (Shapefile)', [QgsProcessing.TypeVectorPolygon]))
        
        # New Time Parameters
        self.addParameter(QgsProcessingParameterDateTime(self.IMAGE_TIME, 'Image Acquisition Date & Time', type=QgsProcessingParameterDateTime.DateTime))
        self.addParameter(QgsProcessingParameterNumber(self.TZ_OFFSET, 'Timezone Offset of Input Time from UTC (e.g., +3 for Dammam)', type=QgsProcessingParameterNumber.Double, defaultValue=0.0))
        
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, 'Buildings with Height'))

    def processAlgorithm(self, parameters, context, feedback):
        buildings_layer = self.parameterAsSource(parameters, self.BUILDINGS, context)
        shadows_layer = self.parameterAsSource(parameters, self.SHADOWS, context)
        image_time_str = self.parameterAsString(parameters, self.IMAGE_TIME, context)
        tz_offset = self.parameterAsDouble(parameters, self.TZ_OFFSET, context)
        
        # --- 1. DATE-TIME PARSING & TIMEZONE CORRECTION ---
        try:
            dt = datetime.fromisoformat(image_time_str)
        except ValueError:
            try:
                dt = datetime.strptime(image_time_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                dt = datetime.strptime(image_time_str, '%Y-%m-%dT%H:%M:%S')
                
        # Convert the user's input time to pure UTC for the astronomical formula
        dt_utc = dt - timedelta(hours=tz_offset)
        
        # --- 2. COORDINATE EXTRACTION ---
        crs_src = buildings_layer.sourceCrs()
        extent = buildings_layer.sourceExtent()
        center_point = extent.center()
        
        crs_dest = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(crs_src, crs_dest, context.transformContext())
        center_wgs84 = transform.transform(center_point)
        
        lat = center_wgs84.y()
        lon = center_wgs84.x()

        # --- 3. SOLAR ANGLES ---
        # Note: We now pass the adjusted dt_utc into the calculator
        sun_azimuth, sun_elevation = self.calculate_solar_position(dt_utc, lat, lon)
        
        feedback.pushInfo(f"Input Time converted to UTC: {dt_utc.strftime('%Y-%m-%d %H:%M:%S')}")
        feedback.pushInfo(f"Calculated Sun Elevation: {sun_elevation:.2f} degrees")
        feedback.pushInfo(f"Calculated Sun Azimuth: {sun_azimuth:.2f} degrees")
        
        # SAFETY CHECK: Warn if the sun is underground
        if sun_elevation < 0:
            feedback.reportError(f"CRITICAL WARNING: Sun Elevation is {sun_elevation:.2f}°. The sun is below the horizon! Check your timestamp and timezone offset.", fatalError=False)

        # --- 4. ELLIPSOIDAL ENGINE ---
        distance_calc = QgsDistanceArea()
        distance_calc.setSourceCrs(crs_src, context.transformContext())
        distance_calc.setEllipsoid('WGS84')

        # --- 5. ADAPT RAY LENGTH & TOLERANCE ---
        if crs_src.isGeographic():
            ray_length = 250.0 / 111320.0
            match_tolerance = 10.0 / 111320.0
        else:
            ray_length = 250.0
            match_tolerance = 10.0

        # --- 6. PREPARE OUTPUT ---
        fields = buildings_layer.fields()
        if fields.indexOf('Height_m') == -1:
            fields.append(QgsField('Height_m', QVariant.Double))
        
        sink, dest_id = self.parameterAsSink(parameters, self.OUTPUT, context, fields, buildings_layer.wkbType(), crs_src)

        # --- 7. SHADOW SPATIAL INDEX ---
        feedback.pushInfo("Indexing shadow vector geometries...")
        shadow_index = QgsSpatialIndex()
        shadow_dict = {}
        for shadow_feat in shadows_layer.getFeatures():
            shadow_index.insertFeature(shadow_feat)
            shadow_dict[shadow_feat.id()] = shadow_feat.geometry()

        # --- 8. DIRECTIONAL MEASUREMENT (VERTEX COMB METHOD) ---
        shadow_direction_azimuth = (sun_azimuth + 180.0) % 360.0
        total = 100.0 / buildings_layer.featureCount() if buildings_layer.featureCount() else 0
        
        for current, bldg_feat in enumerate(buildings_layer.getFeatures()):
            if feedback.isCanceled():
                break
                
            bldg_geom = bldg_feat.geometry()
            
            search_box = bldg_geom.boundingBox()
            search_box.grow(match_tolerance * 2) 
            candidate_shadow_ids = shadow_index.intersects(search_box)
            
            valid_shadows = []
            for sid in candidate_shadow_ids:
                s_geom = shadow_dict[sid]
                if bldg_geom.distance(s_geom) <= match_tolerance:
                    valid_shadows.append(s_geom)
            
            max_shadow_length_m = 0.0
            
            if valid_shadows:
                for vertex in bldg_geom.vertices():
                    start_point = QgsPointXY(vertex)
                    end_point = start_point.project(ray_length, shadow_direction_azimuth)
                    ray_geom = QgsGeometry.fromPolylineXY([start_point, end_point])
                    
                    for s_geom in valid_shadows:
                        if ray_geom.intersects(s_geom):
                            intersection_geom = ray_geom.intersection(s_geom)
                            length_m = distance_calc.measureLength(intersection_geom)
                            
                            if length_m > max_shadow_length_m:
                                max_shadow_length_m = length_m
            
            # --- 9. HEIGHT CALCULATION ---
            height_m = 0.0
            if max_shadow_length_m > 0 and sun_elevation > 0:
                height_m = max_shadow_length_m * math.tan(math.radians(sun_elevation))
            
            out_feat = QgsFeature(fields)
            out_feat.setGeometry(bldg_geom)
            
            attrs = bldg_feat.attributes()
            if len(attrs) < len(fields):
                attrs.append(round(height_m, 2))
            else:
                height_idx = bldg_feat.fields().indexOf('Height_m')
                attrs[height_idx] = round(height_m, 2)
                
            out_feat.setAttributes(attrs)
            sink.addFeature(out_feat, QgsFeatureSink.FastInsert)
            
            feedback.setProgress(int(current * total))

        return {self.OUTPUT: dest_id}

    def calculate_solar_position(self, dt, lat, lon):
        day_of_year = dt.timetuple().tm_yday
        hour = dt.hour + dt.minute/60.0 + dt.second/3600.0
        gamma = (2 * math.pi / 365) * (day_of_year - 1 + (hour - 12) / 24)
        
        eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma) - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
        decl_rad = 0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma) - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma)
        
        time_offset = eqtime + (4 * lon)
        tst = hour * 60 + time_offset
        ha_rad = math.radians((tst / 4) - 180)
        lat_rad = math.radians(lat)
        
        sin_elev = math.sin(lat_rad) * math.sin(decl_rad) + math.cos(lat_rad) * math.cos(decl_rad) * math.cos(ha_rad)
        elev_rad = math.asin(sin_elev)
        elevation = math.degrees(elev_rad)
        
        cos_az = (math.sin(decl_rad) - math.sin(elev_rad) * math.sin(lat_rad)) / (math.cos(elev_rad) * math.cos(lat_rad))
        cos_az = max(min(cos_az, 1.0), -1.0)
        az_rad = math.acos(cos_az)
        
        if ha_rad > 0:
            az_rad = (2 * math.pi) - az_rad
        azimuth = math.degrees(az_rad)
        
        return azimuth, elevation

    def name(self):
        return 'tecrs_height_extractor'

    def displayName(self):
        return 'TECRS Building Height Extractor'

    def createInstance(self):
        return TecrsHeightExtractor()