import sys; sys.path.append('../../')
from uuid import uuid1
from osgeo import gdal, ogr
from typing import Union
from buteo.raster.io import raster_to_metadata
from buteo.vector.io import vector_to_memory, vector_to_metadata, vector_to_path
from buteo.utils import file_exists, remove_if_overwrite, overwrite_required
from buteo.gdal_utils import (
    raster_to_reference, reproject_extent,
    vector_to_reference,
    is_raster,
    is_vector,
    path_to_driver,
    default_options,
    translate_resample_method,
    gdal_nodata_value_from_type,
    align_bbox,
)


def clip_raster(
    raster: Union[str, gdal.Dataset],
    clip_geom: Union[str, ogr.DataSource],
    out_path: Union[str, None]=None,
    resample_alg: str="nearest",
    crop_to_geom: bool=True,
    adjust_bbox: bool=True,
    all_touch: bool=True,
    overwrite: bool=True,
    creation_options: list=[],
    dst_nodata: Union[str, int, float]="infer",
    layer_to_clip: int=0,
) -> Union[gdal.Dataset, str]:
    """ Clips a raster using a vector geometry or the extents of
        a raster.

    Args:
        raster (path | raster): The raster to clip.
        
        clip_geom (path | vector | raster): The geometry to use to clip
        the raster

    **kwargs:
        out_path (path | None): The destination to save to. If None then
        the output is an in-memory raster.

        resample_alg (str): The algorithm to resample the raster. The following
        are available:
            'nearest', 'bilinear', 'cubic', 'cubicSpline', 'lanczos', 'average',
            'mode', 'max', 'min', 'median', 'q1', 'q3', 'sum', 'rms'.
        
        crop_to_geom (bool): Should the extent of the raster be clipped
        to the extent of the clipping geometry.

        all_touch (bool): Should all the pixels touched by the clipped 
        geometry be included or only those which centre lie within the
        geometry.

        overwite (bool): Is it possible to overwrite the out_path if it exists.

        creation_options (list): A list of options for the GDAL creation. Only
        used if an outpath is specified. Defaults are:
            "TILED=YES"
            "NUM_THREADS=ALL_CPUS"
            "BIGG_TIF=YES"
            "COMPRESS=LZW"

        dst_nodata (str | int | float): If dst_nodata is 'infer' the destination nodata
        is the src_nodata if one exists, otherwise it's automatically chosen based
        on the datatype. If an int or a float is given, it is used as the output nodata.

        layer_to_clip (int): The layer in the input vector to use for clipping.

    Returns:
        An in-memory raster. If an out_path is given the output is a string containing
        the path to the newly created raster.
    """
    if not isinstance(layer_to_clip, int):
        raise ValueError("layer_to_clip must be an int.")

    # Throws an error if file exists and overwrite is False.
    overwrite_required(out_path, overwrite)
   
    origin_layer = raster_to_reference(raster)

    raster_metadata = raster_to_metadata(origin_layer)
    origin_projection = raster_metadata["projection_osr"]
    origin_extent = raster_metadata["extent_ogr_geom"]

    # Verify geom
    clip_metadata = None
    clip_ds = None

    if is_raster(clip_geom):
        clip_metadata = raster_to_metadata(clip_geom)
        clip_ds = clip_metadata["extent_ogr"]
    elif is_vector(clip_geom):
        clip_ds = vector_to_reference(clip_geom)
        clip_metadata = vector_to_metadata(clip_geom)
    else:
        if file_exists(clip_geom):
            raise ValueError(f"Unable to parse clip geometry: {clip_geom}")
        else:
            raise ValueError(f"Unable to find clip geometry {clip_geom}")

    if layer_to_clip > (clip_metadata["layer_count"] - 1):
        raise ValueError("Requested an unable layer_to_clip.")

    clip_projection = clip_metadata["projection_osr"]
    clip_extent = clip_metadata["extent_ogr_geom"]

    # Fast check: Does the extent of the two inputs overlap?
    if not origin_extent.Intersects(clip_extent):
        print("WARNING: Geometries did not intersect. Returning None.")
        return None

    # Check if projections match, otherwise reproject target geom.
    if not origin_projection.IsSame(clip_projection):
        clip_metadata["extent"] = reproject_extent(
            clip_metadata["extent"],
            clip_projection,
            origin_projection,
        )

    clip_ds = vector_to_path(clip_ds)

    if clip_ds is None:
        raise ValueError(f"Unable to parse input clip geom: {clip_geom}")

    x_min_og, y_max_og, x_max_og, y_min_og = raster_metadata["extent"]
    output_bounds = (x_min_og, y_min_og, x_max_og, y_max_og) # gdal_warp format

    if crop_to_geom:

        if adjust_bbox:
            output_bounds = align_bbox(
                raster_metadata["extent"],
                clip_metadata["extent"],
                raster_metadata["pixel_width"],
                raster_metadata["pixel_height"],
                warp_format=True,
            )

        else:
            x_min_og, y_max_og, x_max_og, y_min_og = clip_metadata["extent"]
            output_bounds = (x_min_og, y_min_og, x_max_og, y_max_og) # gdal_warp format

    # options
    warp_options = []
    if all_touch:
        warp_options.append("CUTLINE_ALL_TOUCHED=TRUE")
    else:
        warp_options.append("CUTLINE_ALL_TOUCHED=FALSE")

    # formats
    out_name = None
    out_format = None
    out_creation_options = None
    if out_path is None:
        out_name = raster_metadata["name"]
        out_format = "MEM"
        out_creation_options = []
    else:
        out_name = out_path
        out_format = path_to_driver(out_path)
        out_creation_options = default_options(creation_options)

    # nodata
    src_nodata = raster_metadata["nodata_value"]
    out_nodata = None
    if src_nodata is not None:
        out_nodata = src_nodata
    else:
        if dst_nodata == "infer":
            out_nodata = gdal_nodata_value_from_type(raster_metadata["dtype_gdal_raw"])
        else:
            out_nodata = dst_nodata

    # Removes file if it exists and overwrite is True.
    remove_if_overwrite(out_path, overwrite)

    clipped = gdal.Warp(
        out_name,
        origin_layer,
        format=out_format,
        resampleAlg=translate_resample_method(resample_alg),
        targetAlignedPixels=False,
        outputBounds=output_bounds,
        xRes=raster_metadata["pixel_width"],
        yRes=raster_metadata["pixel_height"],
        cutlineDSName=clip_ds,
        cropToCutline=False, # GDAL does this incorrectly when targetAlignedPixels is True.
        creationOptions=out_creation_options,
        warpOptions=warp_options,
        srcNodata=raster_metadata["nodata_value"],
        dstNodata=out_nodata,
        multithread=True,
    )

    if clipped is None:
        print("WARNING: Output is None. Returning empty layer.")

    if out_path is not None:
        return out_path
    else:
        return clipped
