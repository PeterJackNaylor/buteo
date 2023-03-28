"""
### Basic IO functions for working with Rasters ###

This module does standard raster operations related to read, write, and metadata.
"""

# TODO: Copy, seperate, expand, create, delete

# Standard library
import sys; sys.path.append("../../")
import os

# External
import numpy as np
from osgeo import gdal, osr, ogr

# Internal
from buteo.utils import bbox_utils, core_utils, gdal_utils, gdal_enums



def _open_raster(raster, *, writeable=True):
    """ **INTERNAL**. """
    assert isinstance(raster, (gdal.Dataset, str)), "raster must be a string or a gdal.Dataset"

    if isinstance(raster, gdal.Dataset):
        return raster

    if gdal_utils.is_in_memory(raster) or core_utils.file_exists(raster):

        gdal.PushErrorHandler("CPLQuietErrorHandler")
        opened = gdal.Open(raster, gdal.GF_Write) if writeable else gdal.Open(raster, gdal.GF_Read)
        gdal.PopErrorHandler()

        if not isinstance(opened, gdal.Dataset):
            raise ValueError(f"Input raster is not readable. Received: {raster}")

        if opened.GetDescription() == "":
            opened.SetDescription(raster)

        if opened.GetProjectionRef() == "":
            opened.SetProjection(gdal_utils.get_default_projection())
            print(f"WARNING: Input raster {raster} has no projection. Setting to default: EPSG:4326.")

        return opened

    raise ValueError(f"Input raster does not exists. Received: {raster}")


def open_raster(raster, *, writeable=True, allow_lists=True):
    """
    Opens a raster from a path to a raster. Can be in-memory or local. If a
    gdal.Dataset is passed, it is returned. Supports lists. If a list is passed,
    a list is returned with the opened raster.

    Args:
        raster (gdal.Dataset/str/list): A path to a raster or a GDAL dataframe.

    Keyword Args:
        writeable (bool, default=True): If True, the raster is opened in write mode. Default is True.
        allow_lists (bool, default=True): If True, the input can be a list of rasters. Otherwise,
            only a single raster is allowed. Default is True.

    Returns:
        gdal.Dataset/list: A gdal.Dataset or a list of gdal.Datasets.
    """

    core_utils.type_check(raster, [str, gdal.Dataset, [str, gdal.Dataset]], "raster")
    core_utils.type_check(writeable, [bool], "writeable")
    core_utils.type_check(allow_lists, [bool], "allow_lists")

    if not allow_lists and isinstance(raster, (list, tuple)):
        raise ValueError("Input raster must be a single raster. Not a list or tuple.")

    if not allow_lists:
        return _open_raster(raster, writeable=writeable)

    list_input = core_utils.ensure_list(raster)
    list_return = []

    for in_raster in list_input:
        try:
            list_return.append(_open_raster(in_raster, writeable=writeable))
        except Exception:
            raise ValueError(f"Could not open raster: {in_raster}") from None

    if isinstance(raster, list):
        return list_return

    return list_return[0]


def get_projection(raster, wkt=True):
    """
    Gets the projection from a dataset, either as WKT or in another format.
    The input can be a path or a gdal.Dataset.

    Args:
        raster (str/gdal.Dataset): A path to a raster or a gdal.Dataset.

    Keyword Args:
        wkt (bool, default=True): If True, returns the projection as WKT.

    Returns:
        str: The projection of the input raster in the specified format.
    """
    dataset = open_raster(raster)

    if wkt:
        return dataset.GetProjectionRef()

    return dataset.GetProjection()


def _raster_to_metadata(raster):
    """ Internal. """
    core_utils.type_check(raster, [str, gdal.Dataset], "raster")

    dataset = open_raster(raster)

    raster_driver = dataset.GetDriver()

    path = dataset.GetDescription()
    basename = os.path.basename(path)
    split_path = os.path.splitext(basename)
    name = split_path[0]
    ext = split_path[1]

    driver = raster_driver.ShortName

    in_memory = gdal_utils.is_in_memory(raster)

    transform = dataset.GetGeoTransform()

    projection_wkt = dataset.GetProjection()
    projection_osr = osr.SpatialReference()
    projection_osr.ImportFromWkt(projection_wkt)

    width = dataset.RasterXSize
    height = dataset.RasterYSize
    band_count = dataset.RasterCount

    size = [dataset.RasterXSize, dataset.RasterYSize]
    shape = (height, width, band_count)

    pixel_width = abs(transform[1])
    pixel_height = abs(transform[5])

    x_min = transform[0]
    y_max = transform[3]

    x_max = x_min + width * transform[1] + height * transform[2]  # Handle skew
    y_min = y_max + width * transform[4] + height * transform[5]  # Handle skew

    band0 = dataset.GetRasterBand(1)

    datatype_gdal_raw = band0.DataType
    datatype_gdal = gdal.GetDataTypeName(datatype_gdal_raw)

    datatype = gdal_enums.translate_gdal_dtype_to_str(datatype_gdal_raw)

    nodata_value = band0.GetNoDataValue()
    has_nodata = nodata_value is not None

    bbox_ogr = [x_min, x_max, y_min, y_max]

    bboxes = bbox_utils.additional_bboxes(bbox_ogr, projection_osr)

    metadata = {
        "path": path,
        "basename": basename,
        "name": name,
        "ext": ext,
        "transform": transform,
        "in_memory": in_memory,
        "projection_wkt": projection_wkt,
        "projection_osr": projection_osr,
        "width": width,
        "height": height,
        "band_count": band_count,
        "driver": driver,
        "size": size,
        "shape": shape,
        "pixel_width": pixel_width,
        "pixel_height": pixel_height,
        "x_min": x_min,
        "y_max": y_max,
        "x_max": x_max,
        "y_min": y_min,
        "dtype": datatype,
        "dtype_gdal": datatype_gdal,
        "dtype_gdal_raw": datatype_gdal_raw,
        "datatype": datatype,
        "datatype_gdal": datatype_gdal,
        "datatype_gdal_raw": datatype_gdal_raw,
        "nodata_value": nodata_value,
        "has_nodata": has_nodata,
        "is_raster": True,
        "is_vector": False,
        "bbox": bbox_ogr,
        "extent": bbox_ogr,
    }

    for key, value in bboxes.items():
        metadata[key] = value

    def get_bbox_as_vector():
        return bbox_utils.convert_bbox_to_vector(bbox_ogr, projection_osr)


    def get_bbox_as_vector_latlng():
        latlng_wkt = gdal_utils.get_default_projection()
        projection_osr_latlng = osr.SpatialReference()
        projection_osr_latlng.ImportFromWkt(latlng_wkt)

        return bbox_utils.convert_bbox_to_vector(metadata["bbox_latlng"], projection_osr_latlng)


    metadata["get_bbox_vector"] = get_bbox_as_vector
    metadata["get_bbox_vector_latlng"] = get_bbox_as_vector_latlng

    return metadata


def raster_to_metadata(raster, *, allow_lists=True):
    """
    Reads metadata from a raster dataset or a list of raster datasets, and returns a dictionary or a list of dictionaries
    containing metadata information for each raster.

    Args:
        raster (str/gdal.Dataset/list): A path to a raster or a gdal.Dataset,
            or a list of paths to rasters.

    Keyword Args:
        allow_lists (bool, default=True): If True, allows the input to be a
            list of rasters. Otherwise, only a single raster is allowed.

    Returns:
        dict/list of dict: A dictionary or a list of dictionaries containing
            metadata information for each raster.
    """

    core_utils.type_check(raster, [str, gdal.Dataset, [str, gdal.Dataset]], "raster")

    if not allow_lists and isinstance(raster, list):
        raise ValueError("Input raster must be a single raster.")

    if not allow_lists:
        return _raster_to_metadata(raster)

    list_input = core_utils.ensure_list(raster)
    list_return = []

    for in_raster in list_input:
        list_return.append(_raster_to_metadata(in_raster))

    if isinstance(raster, list):
        return list_return

    return list_return[0]


def rasters_are_aligned(
    rasters,
    *,
    same_extent=True,
    same_dtype=False,
    same_nodata=False,
    threshold=0.001,
):
    """
    Verifies whether a list of rasters are aligned.

    Args:
        rasters (list): A list of rasters, either in gdal.Dataset or a string
            referring to the dataset.

    Keyword Args:
        same_extent (bool, default=True): If True, all the rasters should have
            the same extent.
        same_dtype (bool, default=False): If True, all the rasters should have
            the same data type.
        same_nodata (bool, default=False): If True, all the rasters should have
            the same nodata value.
        threshold (float, default=0.001): The threshold for the difference between
            the rasters.

    Returns:
        bool: True if rasters are aligned and optional parameters are True, False otherwise.
    """
    core_utils.type_check(rasters, [[str, gdal.Dataset]], "rasters")
    core_utils.type_check(same_extent, [bool], "same_extent")
    core_utils.type_check(same_dtype, [bool], "same_dtype")
    core_utils.type_check(same_nodata, [bool], "same_nodata")

    if len(rasters) == 1:
        if not gdal_utils.is_raster(rasters[0]):
            raise ValueError(f"Input raster is invalid. {rasters[0]}")

        return True

    base = {
        "projection": None,
        "pixel_width": None,
        "pixel_height": None,
        "x_min": None,
        "y_max": None,
        "transform": None,
        "width": None,
        "height": None,
        "datatype": None,
        "nodata_value": None,
        "projection_wkt": None,
        "projection_osr": None,
    }

    for index, raster in enumerate(rasters):
        meta = _raster_to_metadata(raster)
        if index == 0:
            base["name"] = meta["name"]
            base["projection_wkt"] = meta["projection_wkt"]
            base["projection_osr"] = meta["projection_osr"]
            base["pixel_width"] = meta["pixel_width"]
            base["pixel_height"] = meta["pixel_height"]
            base["x_min"] = meta["x_min"]
            base["y_max"] = meta["y_max"]
            base["transform"] = meta["transform"]
            base["width"] = meta["width"]
            base["height"] = meta["height"]
            base["datatype"] = meta["datatype"]
            base["nodata_value"] = meta["nodata_value"]
        else:
            if meta["projection_wkt"] != base["projection_wkt"]:
                if meta["projection_osr"].IsSame(base["projection_osr"]):
                    print("WARNING: " + base["name"] + " has the same projection as " + meta["name"] + " but they are written differently in WKT format. Consider using the same definition.")
                else:
                    print(base["name"] + " did not match " + meta["name"] + " projection")
                    return False
            if meta["pixel_width"] != base["pixel_width"]:
                if abs(meta["pixel_width"] - base["pixel_width"]) > threshold:
                    print(
                        base["name"] + " did not match " + meta["name"] + " pixel_width"
                    )
                    return False
            if meta["pixel_height"] != base["pixel_height"]:
                if abs(meta["pixel_height"] - base["pixel_height"]) > threshold:
                    print(
                        base["name"]
                        + " did not match "
                        + meta["name"]
                        + " pixel_height"
                    )
                    return False
            if meta["x_min"] != base["x_min"]:
                if abs(meta["x_min"] - base["x_min"]) > threshold:
                    print(base["name"] + " did not match " + meta["name"] + " x_min")
                    return False
            if meta["y_max"] != base["y_max"]:
                if abs(meta["y_max"] - base["y_max"]) > threshold:
                    print(base["name"] + " did not match " + meta["name"] + " y_max")
                    return False
            if same_extent:
                if meta["transform"] != base["transform"]:
                    return False
                if meta["height"] != base["height"]:
                    return False
                if meta["width"] != base["width"]:
                    return False

            if same_dtype:
                if meta["datatype"] != base["datatype"]:
                    return False

            if same_nodata:
                if meta["nodata_value"] != base["nodata_value"]:
                    return False

    return True


def raster_has_nodata(raster):
    """
    Verifies whether a raster has any nodata values.

    Args:
        raster (str): A raster, either in gdal.Dataset or a string
            referring to the dataset.

    Returns:
        bool: True if raster has nodata values, False otherwise.
    """
    core_utils.type_check(raster, [str, gdal.Dataset], "raster")

    ref = open_raster(raster)
    band_count = ref.RasterCount
    for band in range(1, band_count + 1):
        band_ref = ref.GetRasterBand(band)
        if band_ref.GetNoDataValue() is not None:
            ref = None

            return True

    ref = None
    return False


def rasters_have_nodata(rasters):
    """
    Verifies whether a list of rasters have any nodata values.

    Args:
        rasters (list): A list of rasters, either in gdal.Dataset or a string
    """
    core_utils.type_check(rasters, [str, gdal.Dataset, [str, gdal.Dataset]], "raster")

    internal_rasters = core_utils.ensure_list(rasters)
    assert gdal_utils.is_raster_list(internal_rasters), "Invalid raster list."

    has_nodata = False
    for in_raster in internal_rasters:
        if raster_has_nodata(in_raster):
            has_nodata = True
            break

    return has_nodata


def rasters_have_same_nodata(rasters):
    """
    Verifies whether a list of rasters have the same nodata values.

    Args:
        rasters (list): A list of rasters, either in gdal.Dataset or a string
    """
    core_utils.type_check(rasters, [str, gdal.Dataset, [str, gdal.Dataset]], "raster")

    internal_rasters = core_utils.ensure_list(rasters)
    assert gdal_utils.is_raster_list(internal_rasters), "Invalid raster list."

    nodata_values = []
    for in_raster in internal_rasters:
        ref = open_raster(in_raster)
        band_count = ref.RasterCount
        for band in range(1, band_count + 1):
            band_ref = ref.GetRasterBand(band)
            nodata_values.append(band_ref.GetNoDataValue())

        ref = None

    return len(set(nodata_values)) == 1


def get_first_nodata_value(raster):
    """
    Gets the first nodata value from a raster.

    Args:
        raster (str/gdal.Dataset): The raster to get the nodata value from.
    """
    core_utils.type_check(raster, [str, gdal.Dataset], "raster")

    nodata = None

    ref = open_raster(raster)
    band_count = ref.RasterCount
    for band in range(1, band_count + 1):
        band_ref = ref.GetRasterBand(band)
        nodata_value = band_ref.GetNoDataValue()
        if nodata_value is not None:
            nodata = nodata_value
            break

    ref = None
    return nodata


def raster_to_array(
    raster,
    *,
    bands='all',
    masked="auto",
    filled=False,
    fill_value=None,
    bbox=None,
    pixel_offsets=None,
):
    """
    Converts a raster or a list of rasters into a NumPy array.

    Args:
        raster (gdal.Dataset/str/list): Raster(s) to convert.

    Keyword Args:
        bands (list/str/int, default="all"): Bands from the raster to convert to a numpy array.
            Can be "all", an int, or a list of integers, or a single integer.
        masked (bool/str, default="auto"): If the array contains nodata values, determines whether
            the resulting array should be a masked numpy array or a regular numpy array. If "auto",
            the array will be masked only if the raster has nodata values.
        filled (bool, default=False): If the array contains nodata values, determines whether
            the resulting array should be a filled numpy array or a masked array.
        fill_value (int/float, default=None): Value to fill the array with if filled is True.
            If None, the nodata value of the raster is used.
        bbox (list, default=None): A list of `[xmin, xmax, ymin, ymax]` to use as
            the extent of the raster. Uses coordinates and the OGR format.
        pixel_offsets (list, default=None): A list of
            `[x_offset, y_offset, x_size, y_size]` to use as the extent of the
            raster. Uses pixel offsets and the OGR format.

    Returns:
        np.ndarray: A numpy array in the 3D channel-last format.
    """
    core_utils.type_check(raster, [str, gdal.Dataset, [str, gdal.Dataset]], "raster")
    core_utils.type_check(bands, [int, [int], str], "bands")
    core_utils.type_check(filled, [bool], "filled")
    core_utils.type_check(fill_value, [int, float, None], "fill_value")
    core_utils.type_check(masked, [bool, str], "masked")
    core_utils.type_check(bbox, [list, None], "bbox")
    core_utils.type_check(pixel_offsets, [list, None], "pixel_offsets")

    if masked not in ["auto", True, False]:
        raise ValueError(f"masked must be 'auto', True, or False. {masked} was provided.")

    if bbox is not None and pixel_offsets is not None:
        raise ValueError("Cannot use both bbox and pixel_offsets.")

    internal_rasters = core_utils.ensure_list(raster)

    if not gdal_utils.is_raster_list(internal_rasters):
        raise ValueError(f"An input raster is invalid. {internal_rasters}")

    internal_rasters = gdal_utils.get_path_from_dataset_list(internal_rasters, dataset_type="raster")

    if len(internal_rasters) > 1 and not rasters_are_aligned(internal_rasters, same_extent=True, same_dtype=False):
        raise ValueError(
            "Cannot merge rasters that are not aligned, have dissimilar extent or dtype, when stack=True."
        )

    # Read metadata
    metadata = raster_to_metadata(internal_rasters[0])
    dtype = metadata["dtype"]
    shape = metadata["shape"]

    # Determine output shape
    x_offset, y_offset, x_size, y_size = 0, 0, shape[1], shape[0]

    if pixel_offsets is not None:
        x_offset, y_offset, x_size, y_size = pixel_offsets

        if x_offset < 0 or y_offset < 0:
            raise ValueError("Pixel offsets cannot be negative.")

        if x_offset + x_size > shape[1] or y_offset + y_size > shape[0]:
            raise ValueError("Pixel offsets are outside of raster.")

    elif bbox is not None:
        if not bbox_utils.bboxes_intersect(metadata["bbox"], bbox):
            raise ValueError("Extent is outside of raster.")

        x_offset, y_offset, x_size, y_size = bbox_utils.get_pixel_offsets(metadata["transform"], bbox)

    output_shape = (y_size, x_size, len(internal_rasters) * shape[2])

    # Determine nodata and value
    if masked == "auto":
        has_nodata = rasters_have_nodata(internal_rasters)
        if has_nodata:
            masked = True
        else:
            masked = False

    output_nodata_value = None
    if masked or filled:
        output_nodata_value = get_first_nodata_value(internal_rasters[0])

        if output_nodata_value is None:
            output_nodata_value = np.nan

        if filled and fill_value is None:
            fill_value = output_nodata_value

    # Create output array
    if masked:
        output_arr = np.ma.empty(output_shape, dtype=dtype)
        output_arr.mask = True

        if filled:
            output_arr.fill_value = fill_value
        else:
            output_arr.fill_value = output_nodata_value
    else:
        output_arr = np.empty(output_shape, dtype=dtype)


    band_idx = 0
    for in_raster in internal_rasters:

        ref = open_raster(in_raster)

        metadata = raster_to_metadata(ref)
        band_count = metadata["band_count"]

        if band_count == 0:
            raise ValueError("The input raster does not have any valid bands.")

        if bands == "all":
            bands = -1

        internal_bands = gdal_utils.to_band_list(bands, metadata["band_count"])

        for band in internal_bands:
            band_ref = ref.GetRasterBand(band + 1)
            band_nodata_value = band_ref.GetNoDataValue()

            if pixel_offsets is not None or bbox is not None:
                arr = band_ref.ReadAsArray(x_offset, y_offset, x_size, y_size)
            else:
                arr = band_ref.ReadAsArray()

            if arr.shape[0] == 0 or arr.shape[1] == 0:
                raise RuntimeWarning("The output data has no rows or columns.")

            if masked or filled:
                if band_nodata_value is not None:
                    masked_arr = np.ma.array(arr, mask=arr == band_nodata_value, copy=False)
                    masked_arr.fill_value = output_nodata_value

                    if filled:
                        arr = np.ma.getdata(masked_arr.filled(fill_value))
                    else:
                        arr = masked_arr

            output_arr[:, :, band_idx] = arr

            band_idx += 1

        ref = None

    return output_arr


def array_to_raster(
    array,
    *,
    reference,
    out_path=None,
    set_nodata="arr",
    allow_mismatches=False,
    pixel_offsets=None,
    bbox=None,
    overwrite=True,
    creation_options=None,
):
    """
    Turns a NumPy array into a GDAL dataset or exported
    as a raster using a reference raster.

    Args:
        array (np.ndarray): The numpy array to convert.
        reference (str/gdal.Dataset): The reference raster to use for the output.

    Keyword Args:
        out_path (path, default=None): The destination to save to.
        set_nodata (bool/float/int, default="arr"): Can be set to
            • "arr": The nodata value will be the same as the NumPy array.
            • "ref": The nodata value will be the same as the reference raster.
            • value: The nodata value will be the value provided.
        allow_mismatches (bool, default=False): If True, the array can have a
            different shape than the reference raster.
        pixel_offsets (list, default=None): If provided, the array will be
            written to the reference raster at the specified pixel offsets.
            The list should be in the format [x_offset, y_offset, x_size, y_size].
        bbox (list, default=None): If provided, the array will be written to
            the reference raster at the specified bounding box.
            The list should be in the format [min_x, min_y, max_x, max_y].
        overwrite (bool, default=True): If the file exists, should it be
            overwritten?
        creation_options (list, default=["TILED=YES", "NUM_THREADS=ALL_CPUS",
            "BIGTIFF=YES", "COMPRESS=LZW"]): List of GDAL creation options.

    Returns:
        str: The filepath to the newly created raster(s).
    """
    core_utils.type_check(array, [np.ndarray, np.ma.MaskedArray], "array")
    core_utils.type_check(reference, [str, gdal.Dataset], "reference")
    core_utils.type_check(out_path, [str, None], "out_path")
    core_utils.type_check(overwrite, [bool], "overwrite")
    core_utils.type_check(pixel_offsets, [[int, float], None], "pixel_offsets")
    core_utils.type_check(allow_mismatches, [bool], "allow_mismatches")
    core_utils.type_check(set_nodata, [int, float, str, None], "set_nodata")
    core_utils.type_check(creation_options, [[str], None], "creation_options")

    # Verify the numpy array
    if (
        array.size == 0
        or array.ndim < 2
        or array.ndim > 3
    ):
        raise ValueError(f"Input array is invalid {array}")

    if set_nodata not in ["arr", "ref"]:
        core_utils.type_check(set_nodata, [int, float], "set_nodata")

    if pixel_offsets is not None:
        if len(pixel_offsets) != 4:
            raise ValueError("pixel_offsets must be a list of 4 values.")

    if pixel_offsets is not None and bbox is not None:
        raise ValueError("pixel_offsets and bbox cannot be used together.")

    # Parse the driver
    driver_name = "GTiff" if out_path is None else gdal_utils.path_to_driver_raster(out_path)
    if driver_name is None:
        raise ValueError(f"Unable to parse filetype from path: {out_path}")

    driver = gdal.GetDriverByName(driver_name)
    if driver is None:
        raise ValueError(f"Error while creating driver from extension: {out_path}")

    # How many bands?
    bands = 1
    if array.ndim == 3:
        bands = array.shape[2]

    output_name = None
    if out_path is None:
        output_name = gdal_utils.create_memory_path("array_to_raster.tif", add_uuid=True)
    else:
        output_name = out_path

    core_utils.remove_if_required(output_name, overwrite)

    metadata = raster_to_metadata(reference)
    reference_nodata = metadata["nodata_value"]

    # handle nodata. GDAL python throws error if conversion in not explicit.
    if reference_nodata is not None:
        reference_nodata = float(reference_nodata)
        if (reference_nodata).is_integer() is True:
            reference_nodata = int(reference_nodata)

    # Handle nodata
    input_nodata = None
    if np.ma.is_masked(array) is True:
        input_nodata = array.get_fill_value()  # type: ignore (because it's a masked array.)

    destination_dtype = gdal_enums.translate_str_to_gdal_dtype(array.dtype)

    # Weird double issue with GDAL and numpy. Cast to float or int
    if input_nodata is not None:
        input_nodata = float(input_nodata)
        if (input_nodata).is_integer() is True:
            input_nodata = int(input_nodata)

    if (metadata["width"] != array.shape[1] or metadata["height"] != array.shape[0]) and pixel_offsets is None and bbox is None:
        if not allow_mismatches:
            raise ValueError(f"Input array and raster are not of equal size. Array: {array.shape[:2]} Raster: {metadata['width'], metadata['height']}")

        print("WARNING: Input array and raster are not of equal size.")

    if bbox is not None:
        pixel_offsets = bbox_utils.get_pixel_offsets(metadata["transform"], bbox)

    if pixel_offsets is not None:
        x_offset, y_offset, x_size, y_size = pixel_offsets

        if array.ndim == 3:
            array = array[:y_size, :x_size:, :] # numpy is col, row order
        else:
            array = array[:y_size, x_size]

        metadata["transform"] = (
            metadata["transform"][0] + (x_offset * metadata["pixel_width"]),
            metadata["transform"][1],
            metadata["transform"][2],
            metadata["transform"][3] - (y_offset * metadata["pixel_height"]),
            metadata["transform"][4],
            metadata["transform"][5],
        )

    destination = driver.Create(
        output_name,
        array.shape[1],
        array.shape[0],
        bands,
        destination_dtype,
        gdal_utils.default_creation_options(creation_options),
    )

    destination.SetProjection(metadata["projection_wkt"])
    destination.SetGeoTransform(metadata["transform"])

    for band_idx in range(bands):
        band = destination.GetRasterBand(band_idx + 1)
        band.SetColorInterpretation(gdal.GCI_Undefined)

        if bands > 1 or array.ndim == 3:
            band.WriteArray(array[:, :, band_idx])
        else:
            band.WriteArray(array)

        if set_nodata == "ref" and reference_nodata is not None:
            band.SetNoDataValue(reference_nodata)
        elif set_nodata == "arr" and input_nodata is not None:
            band.SetNoDataValue(input_nodata)
        elif isinstance(set_nodata, (int, float)):
            band.SetNoDataValue(set_nodata)

    destination.FlushCache()
    destination = None

    return output_name


def _raster_set_datatype(
    raster,
    dtype_str,
    out_path=None,
    *,
    overwrite=True,
    creation_options=None,
):
    """ **INTERNAL**. """
    assert isinstance(raster, (str, gdal.Dataset)), "raster must be a string or a GDAL.Dataset."
    assert isinstance(dtype_str, str), "dtype_str must be a string."
    assert len(dtype_str) > 0, "dtype_str must be a non-empty string."

    if not gdal_utils.is_raster(raster):
        raise ValueError(f"Unable to open input raster: {raster}")

    ref = open_raster(raster)
    metadata = raster_to_metadata(ref)

    path = ""
    if out_path is None:
        path = gdal_utils.create_memory_path(metadata["basename"], add_uuid=True)

    elif core_utils.folder_exists(out_path):
        path = os.path.join(out_path, os.path.basename(gdal_utils.get_path_from_dataset(ref)))

    elif core_utils.folder_exists(core_utils.path_to_folder(out_path)):
        path = out_path

    elif core_utils.is_valid_mem_path(out_path):
        path = out_path

    else:
        raise ValueError(f"Unable to find output folder: {out_path}")

    driver_name = gdal_utils.path_to_driver_raster(path)
    driver = gdal.GetDriverByName(driver_name)

    if driver is None:
        raise ValueError(f"Unable to get driver for raster: {raster}")

    core_utils.remove_if_required(path, overwrite)

    if isinstance(dtype_str, str):
        dtype_str = dtype_str.lower()

    copy = driver.Create(
        path,
        metadata["height"],
        metadata["width"],
        metadata["band_count"],
        gdal_enums.translate_str_to_gdal_dtype(dtype_str),
        gdal_utils.default_creation_options(creation_options),
    )

    if copy is None:
        raise ValueError(f"Unable to create output raster: {path}")

    copy.SetProjection(metadata["projection_wkt"])
    copy.SetGeoTransform(metadata["transform"])

    array = raster_to_array(ref)

    for band_idx in range(metadata["band_count"]):
        band = copy.GetRasterBand(band_idx + 1)
        band.WriteArray(array[:, :, band_idx])

        if metadata["nodata_value"] is not None:
            band.SetNoDataValue(metadata["nodata_value"])

    ref = None

    return path


def raster_set_datatype(
    raster,
    dtype,
    out_path=None,
    *,
    overwrite=True,
    allow_lists=True,
    creation_options=None,
):
    """
    Converts the datatype of a raster.

    Args:
        raster (str/gdal.Dataset/list): The input raster(s) for which the
            datatype will be changed.
        dtype (str): The target datatype for the output raster(s).

    Keyword Args:
        out_path (path/list, default=None): The output location for the
            processed raster(s).
        overwrite (bool, default=True): Determines whether to overwrite
            existing files with the same name.
        allow_lists (bool, default=True): Allows processing multiple
            rasters as a list. If set to False, only single rasters are
            accepted.
        creation_options (list, default=["TILED=YES", "NUM_THREADS=ALL_CPUS",
            "BIGTIFF=YES", "COMPRESS=LZW"]): A list of GDAL creation options
            for the output raster(s).

    Returns:
        str/list: The filepath(s) of the newly created raster(s) with
            the specified datatype.
    """
    core_utils.type_check(raster, [str, gdal.Dataset, [str, gdal.Dataset]], "raster")
    core_utils.type_check(dtype, [str], "dtype")
    core_utils.type_check(out_path, [list, str, None], "out_path")
    core_utils.type_check(overwrite, [bool], "overwrite")
    core_utils.type_check(allow_lists, [bool], "allow_lists")
    core_utils.type_check(creation_options, [list, None], "creation_options")

    if not allow_lists:
        if isinstance(raster, list):
            raise ValueError("allow_lists is False, but the input raster is a list.")

        return _raster_set_datatype(
            raster,
            dtype,
            out_path=out_path,
            overwrite=overwrite,
            creation_options=creation_options,
        )

    add_uuid = out_path is None

    raster_list = core_utils.ensure_list(raster)
    path_list = gdal_utils.create_output_path_list(raster_list, out_path, overwrite=overwrite, add_uuid=add_uuid)

    output = []
    for index, in_raster in enumerate(raster_list):
        path = _raster_set_datatype(
            in_raster,
            dtype,
            out_path=path_list[index],
            overwrite=overwrite,
            creation_options=gdal_utils.default_creation_options(creation_options),
        )

        output.append(path)

    if isinstance(raster, list):
        return output

    return output[0]



def stack_rasters(
    rasters,
    out_path=None,
    *,
    overwrite=True,
    dtype=None,
    creation_options=None,
):
    """
    Stacks a list of rasters. Must be aligned.

    ## Args:
    `rasters` (_list_): List of rasters to stack. </br>

    ## Kwargs
    `out_path` (_str_/_None_): The destination to save to. (Default: **None**)</br>
    `overwrite` (_bool_): If the file exists, should it be overwritten? (Default: **True**) </br>
    `dtype` (_str_): The data type of the output raster. (Default: **None**)</br>
    `creation_options` (_list_): List of **GDAL** creation options. Defaults are: </br>
    &emsp; • "TILED=YES" </br>
    &emsp; • "NUM_THREADS=ALL_CPUS" </br>
    &emsp; • "BIG_TIFF=YES" </br>
    &emsp; • "COMPRESS=LZW" </br>

    ## Returns:
    (_str_/_list_): The filepath(s) to the newly created raster(s).
    """
    core_utils.type_check(rasters, [[str, gdal.Dataset]], "rasters")
    core_utils.type_check(out_path, [str, None], "out_path")
    core_utils.type_check(overwrite, [bool], "overwrite")
    core_utils.type_check(dtype, [str, None], "dtype")
    core_utils.type_check(creation_options, [[str], None], "creation_options")

    assert gdal_utils.is_raster_list(rasters), "Input rasters must be a list of rasters."

    if not rasters_are_aligned(rasters, same_extent=True):
        raise ValueError("Rasters are not aligned. Try running align_rasters.")

    # Ensures that all the input rasters are valid.
    raster_list = gdal_utils.get_path_from_dataset_list(rasters)

    if out_path is not None and core_utils.path_to_ext(out_path) == ".vrt":
        raise ValueError("Please use stack_rasters_vrt to create vrt files.")

    # Parse the driver
    driver_name = "GTiff" if out_path is None else gdal_utils.path_to_driver_raster(out_path)
    if driver_name is None:
        raise ValueError(f"Unable to parse filetype from path: {out_path}")

    driver = gdal.GetDriverByName(driver_name)
    if driver is None:
        raise ValueError(f"Error while creating driver from extension: {out_path}")

    output_name = None
    if out_path is None:
        output_name = gdal_utils.create_memory_path("stack_rasters.tif", add_uuid=True)
    else:
        output_name = out_path

    core_utils.remove_if_required(output_name, overwrite)

    raster_dtype = raster_to_metadata(raster_list[0])["datatype_gdal_raw"]

    datatype = raster_dtype
    if dtype is not None:
        datatype = gdal_enums.translate_str_to_gdal_dtype(dtype)

    nodata_values = []
    nodata_missmatch = False
    nodata_value = None
    total_bands = 0
    metadatas = []
    for raster in raster_list:
        metadata = raster_to_metadata(raster)
        metadatas.append(metadata)

        nodata_value = metadata["nodata_value"]
        total_bands += metadata["band_count"]

        if nodata_missmatch is False:
            for ndv in nodata_values:
                if nodata_missmatch:
                    continue

                if metadata["nodata_value"] != ndv:
                    print(
                        "WARNING: NoDataValues of input rasters do not match. Removing nodata."
                    )
                    nodata_missmatch = True

        nodata_values.append(metadata["nodata_value"])

    if nodata_missmatch:
        nodata_value = None

    destination = driver.Create(
        output_name,
        metadatas[0]["width"],
        metadatas[0]["height"],
        total_bands,
        datatype,
        gdal_utils.default_creation_options(creation_options),
    )

    destination.SetProjection(metadatas[0]["projection_wkt"])
    destination.SetGeoTransform(metadatas[0]["transform"])

    bands_added = 0
    for index, raster in enumerate(raster_list):
        metadata = metadatas[index]
        band_count = metadata["band_count"]

        array = raster_to_array(raster)

        for band_idx in range(band_count):
            dst_band = destination.GetRasterBand(bands_added + 1)
            dst_band.WriteArray(array[:, :, band_idx])

            if nodata_value is not None:
                dst_band.SetNoDataValue(nodata_value)

            bands_added += 1

    return output_name


def stack_rasters_vrt(
    rasters,
    out_path,
    seperate=True,
    *,
    resample_alg="nearest",
    srcNodata=None,
    VRTNodata=None,
    hideNodata=None,
    options=None,
    overwrite=True,
    reference=None,
    creation_options=None,
):
    """
    Stacks a list of rasters into a virtual rasters (.vrt).

    ## Args:
    `rasters` (_list_): List of rasters to stack. </br>
    `out_path` (_str_): The destination to save to. </br>

    ## Kwargs:
    `seperate` (_bool_): If the raster bands should be seperated. (Default: **True**) </br>
    `resample_alg` (_str_): The resampling algorithm to use. (Default: **nearest**) </br>
    `srcNodata` (_float_): The nodata value to use. (Default: **None**) </br>
    `VRTNodata` (_float_): The nodata value to use. (Default: **None**) </br>
    `hideNodata` (_bool_): If the nodata value should be hidden. (Default: **None**) </br>
    `options` (_list_): List of VRT options for GDAL. (Default: **()** </br>
    `overwrite` (_bool_): If the file exists, should it be overwritten? (Default: **True**) </br>
    `reference` (_str_): The reference raster to use. (Default: **None**) </br>
    `creation_options` (_list_): List of **GDAL** creation options. Defaults are: </br>
    * &emsp; • "TILED=YES"
    * &emsp; • "NUM_THREADS=ALL_CPUS"
    * &emsp; • "BIGG_TIF=YES"
    * &emsp; • "COMPRESS=LZW"

    ## Returns:
    (_str_): The filepath to the newly created VRT raster.
    """
    core_utils.type_check(rasters, [[str, gdal.Dataset]], "rasters")
    core_utils.type_check(out_path, [str], "out_path")
    core_utils.type_check(seperate, [bool], "seperate")
    core_utils.type_check(resample_alg, [str], "resample_alg")
    core_utils.type_check(options, [tuple, None], "options")
    core_utils.type_check(overwrite, [bool], "overwrite")
    core_utils.type_check(creation_options, [[str], None], "creation_options")

    resample_algorithm = gdal_enums.translate_resample_method(resample_alg)

    if reference is not None:
        meta = raster_to_metadata(reference)
        options = gdal.BuildVRTOptions(
            resampleAlg=resample_algorithm,
            separate=seperate,
            outputBounds=bbox_utils.convert_ogr_bbox_to_gdal_bbox(meta["bbox"]),
            xRes=meta["pixel_width"],
            yRes=meta["pixel_height"],
            targetAlignedPixels=True,
            srcNodata=srcNodata,
            VRTNodata=VRTNodata,
            hideNodata=hideNodata,
        )
    else:
        options = gdal.BuildVRTOptions(resampleAlg=resample_algorithm, separate=seperate)

    if options is None:
        options = ()

    vrt = gdal.BuildVRT(out_path, rasters, options=options)

    if vrt is None:
        raise ValueError(f"Error while creating VRT from rasters: {rasters}")

    return out_path


def rasters_intersect(raster1, raster2):
    """
    Checks if two rasters intersect using their latlong boundaries.

    ## Args:
    `raster1` (_str_/gdal.Dataset): The first raster. </br>
    `raster2` (_str_/gdal.Dataset): The second raster. </br>

    ## Returns:
    (_bool_): If the rasters intersect.
    """
    core_utils.type_check(raster1, [str, gdal.Dataset, [str, gdal.Dataset]], "raster1")
    core_utils.type_check(raster2, [list, str, gdal.Dataset], "raster2")

    meta1 = raster_to_metadata(raster1)
    meta2 = raster_to_metadata(raster2)

    return meta1["bbox_geom_latlng"].Intersects(meta2["bbox_geom_latlng"])


def rasters_intersection(raster1, raster2):
    """
    Get the latlng intersection of two rasters.

    ## Args:
    `raster1` (_str_/_gdal.Dataset_): The first raster. </br>
    `raster2` (_str_/_gdal.Dataset_): The second raster. </br>

    ## Returns:
    (_ogr.DataSource_): The latlng intersection of the two rasters.
    """
    core_utils.type_check(raster1, [str, gdal.Dataset, [str, gdal.Dataset]], "raster1")
    core_utils.type_check(raster2, [str, gdal.Dataset, [str, gdal.Dataset]], "raster2")

    if not rasters_intersect(raster1, raster2):
        raise ValueError("Rasters do not intersect.")

    meta1 = raster_to_metadata(raster1)
    meta2 = raster_to_metadata(raster2)

    intersection = meta1["bbox_geom_latlng"].Intersection(meta2["bbox_geom_latlng"])

    return gdal_utils.convert_geom_to_vector(intersection)


def get_overlap_fraction(raster1, raster2):
    """
    Get the fraction of the overlap between two rasters. (e.g. 0.9 for mostly overlapping rasters)

    ## Args:
    `raster1` (_str_/_gdal.Dataset_): The master raster. </br>
    `raster2` (_str_/_gdal.Dataset_): The test raster. </br>

    ## Returns:
    (_float_): A value representing the degree of overlap **(0-1)**
    """
    core_utils.type_check(raster1, [str, gdal.Dataset, [str, gdal.Dataset]], "raster1")
    core_utils.type_check(raster2, [str, gdal.Dataset, [str, gdal.Dataset]], "raster2")

    if not rasters_intersect(raster1, raster2):
        return 0.0

    meta1 = raster_to_metadata(raster1)["bbox_geom_latlng"]
    meta2 = raster_to_metadata(raster2)["bbox_geom_latlng"]

    try:
        intersection = meta1.Intersection(meta2)
    except Exception:
        return 0.0

    overlap = intersection.GetArea() / meta1.GetArea()

    return overlap


def create_raster_from_array(
    arr,
    out_path=None,
    pixel_size=10.0,
    x_min=0.0,
    y_max=0.0,
    projection="EPSG:3857",
    creation_options=None,
    overwrite=True,
):
    """ Create a raster from a numpy array. """
    core_utils.type_check(arr, [np.ndarray, np.ma.MaskedArray], "arr")
    core_utils.type_check(out_path, [str, None], "out_path")
    core_utils.type_check(pixel_size, [int, float, [int, float]], "pixel_size")
    core_utils.type_check(x_min, [int, float], "x_min")
    core_utils.type_check(y_max, [int, float], "y_max")
    core_utils.type_check(projection, [int, str, gdal.Dataset, ogr.DataSource, osr.SpatialReference], "projection")
    core_utils.type_check(creation_options, [[str], None], "creation_options")
    core_utils.type_check(overwrite, [bool], "overwrite")

    assert arr.ndim in [2, 3], "Array must be 2 or 3 dimensional (3rd dimension considered bands.)"

    if arr.ndim == 2:
        arr = arr[:, :, np.newaxis]

    # Parse the driver
    driver_name = "GTiff" if out_path is None else gdal_utils.path_to_driver_raster(out_path)
    if driver_name is None:
        raise ValueError(f"Unable to parse filetype from path: {out_path}")

    driver = gdal.GetDriverByName(driver_name)
    if driver is None:
        raise ValueError(f"Error while creating driver from extension: {out_path}")

    output_name = None
    if out_path is None:
        output_name = gdal_utils.create_memory_path("raster_from_array.tif", add_uuid=True)
    else:
        output_name = out_path

    core_utils.remove_if_required(output_name, overwrite)

    height = arr.shape[0]
    width = arr.shape[1]
    bands = arr.shape[2]

    destination = driver.Create(
        output_name,
        width,
        height,
        bands,
        gdal_enums.translate_str_to_gdal_dtype(arr.dtype.name),
        gdal_utils.default_creation_options(creation_options),
    )

    parsed_projection = gdal_utils.parse_projection(projection, return_wkt=True)

    destination.SetProjection(parsed_projection)

    pixel_width = pixel_size if isinstance(pixel_size, (int,  float)) else pixel_size[0]
    pixel_height = pixel_size if isinstance(pixel_size, (int,  float)) else pixel_size[1]

    transform = [x_min, pixel_width, 0, y_max, 0, -pixel_height] # negative for north-up

    destination.SetGeoTransform(transform)

    nodata = None
    if isinstance(arr, np.ma.MaskedArray):
        nodata = arr.fill_value

    for idx in range(0, bands):
        dst_band = destination.GetRasterBand(idx + 1)
        dst_band.WriteArray(arr[:, :, idx])

        if nodata is not None:
            dst_band.SetNoDataValue(nodata)

    return output_name


def create_grid_with_coordinates(raster):
    """Create a grid of coordinates from a raster. Format is (x, y, xy). """
    core_utils.type_check(raster, [str, gdal.Dataset], "raster")

    meta = raster_to_metadata(raster)

    step_x = meta["pixel_width"]
    size_x = meta["width"]
    start_x = meta["x_min"]
    stop_x = meta["x_max"]

    step_y = -meta["pixel_height"]
    size_y = meta["height"]
    start_y = meta["y_max"]
    stop_y = meta["y_min"]

    x_adj = step_x / 2
    y_adj = step_y / 2

    x_vals = np.linspace(start_x + x_adj, stop_x - x_adj, size_x, dtype=np.float32)
    y_vals = np.linspace(start_y - y_adj, stop_y + y_adj, size_y, dtype=np.float32)

    xx, yy = np.meshgrid(x_vals, y_vals)
    grid = np.dstack((xx, yy))

    return grid
