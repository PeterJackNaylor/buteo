from osgeo import osr, ogr
from typing import Dict, Tuple, Union, List, Any, Optional
from mypy_extensions import TypedDict

Number = Union[float, int]

Metadata_raster = TypedDict(
    "Metadata_raster",
    {
        "path": str,
        "basename": str,
        "name": str,
        "ext": str,
        "transform": List[Number],
        "projection": str,
        "projection_osr": osr.SpatialReference,
        "width": int,
        "height": int,
        "band_count": int,
        "driver": str,
        "size": List[int],
        "shape": Tuple[Number, Number, Number],
        "pixel_width": Number,
        "pixel_height": Number,
        "x_min": Number,
        "y_max": Number,
        "x_max": Number,
        "y_min": Number,
        "datatype": str,
        "datatype_gdal": str,
        "datatype_gdal_raw": int,
        "nodata_value": Optional[Number],
        "has_nodata": bool,
        "is_vector": bool,
        "is_raster": bool,
        "extent": List[Number],
        "extent_ogr": List[Number],
        "extent_gdal_warp": List[Number],
        "extent_dict": Dict[str, Number],
        "extent_wkt": Optional[str],
        "extent_datasource": Optional[ogr.gdal.Dataset],
        "extent_geom": Optional[ogr.Geometry],
        "extent_latlng": Optional[List[Number]],
        "extent_gdal_warp_latlng": Optional[List[Number]],
        "extent_ogr_latlng": Optional[List[Number]],
        "extent_dict_latlng": Optional[Dict[str, Number]],
        "extent_wkt_latlng": Optional[str],
        "extent_datasource_latlng": Optional[ogr.gdal.Dataset],
        "extent_geom_latlng": Optional[ogr.Geometry],
        "extent_geojson": Optional[str],
        "extent_geojson_dict": Optional[Dict[Any, Any]],
    },
)


Metadata_raster_comp = TypedDict(
    "Metadata_raster_comp",
    {
        "projection": Optional[str],
        "pixel_width": Optional[Number],
        "pixel_height": Optional[Number],
        "x_min": Optional[Number],
        "y_max": Optional[Number],
        "transform": Optional[List[Number]],
        "width": Optional[int],
        "height": Optional[int],
        "datatype": Optional[str],
        "nodata_value": Optional[Number],
    },
)
