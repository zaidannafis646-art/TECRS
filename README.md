TECRS Building Height Extractor

The TECRS Building Height Extractor is a QGIS Processing Plugin designed to automate the extraction of 3D building heights from 2D Very High-Resolution (VHR) satellite imagery (e.g., SuperView-2, WorldView).
By utilizing building footprints and extracted shadow polygons, the plugin calculates the exact sun position at the time of image capture and uses a Vertex Comb Ray-Casting algorithm to accurately measure shadow lengths and calculate building heights.

How It Works
1. The plugin relies on basic trigonometry (H = L * tan(α)).
2. Computes the Sun Azimuth and Sun Elevation (α) using the image timestamp and local coordinates.
3. Projects directional rays from the building to intersect nearby shadow polygons.
4. Measures the maximum overlapping line segment to find the true shadow length (L).
5. Calculates the height and populates a new Height_m field in the output vector layer.

Installation

Option A: Via QGIS Plugin Repository
1. Open QGIS.
2. Go to Plugins -> Manage and Install Plugins...
3. Search for TECRS Building Height Extractor and click Install Plugin.

Option B: Manual Installation
1. Download the latest .zip release from this repository.
2. Open QGIS.
3. Go to Plugins -> Manage and Install Plugins... -> Install from ZIP.
4. Select the downloaded .zip file and click Install Plugin.

Once installed, the tool can be found in your Processing Toolbox:
Processing Toolbox -> TECRS -> Urban Analysis -> Building Height Extractor

Required Inputs:
1. Building Footprints: A polygon vector layer of your buildings.
2. Shadow Polygons: A polygon vector layer of your extracted shadows.
3. Image Acquisition Date & Time: The exact timestamp the satellite image was taken.
4. Timezone Offset: The offset from UTC (e.g., if the timestamp is local time in Dammam, use 3.0. If the timestamp is already in UTC, use 0.0).


Contributing

Contributions, issues, and feature requests are welcome! Feel free to check the issues page.

License

This project is licensed under the GPL-3.0 License. Developed by TECRS.
