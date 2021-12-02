import sys

sys.path.append("..")
sys.path.append("../../")

from numba import jit, prange
from buteo.raster.io import (
    raster_to_array,
    array_to_raster,
    rasters_intersect,
)
from buteo.raster.align import rasters_are_aligned, align_rasters
from buteo.raster.clip import clip_raster
from buteo.raster.reproject import reproject_raster
from buteo.raster.proximity import calc_proximity
from buteo.filters.kernel_generator import create_kernel
from buteo.utils import progress
from osgeo import gdal
import numpy as np
import os
import datetime
from uuid import uuid4


def name_to_date(path):
    timetag = os.path.basename(path).split("_")[5]
    return datetime.datetime.strptime(timetag, "%Y%m%dT%H%M%S").replace(
        tzinfo=datetime.timezone.utc
    )


def sort_rasters(rasters):
    by_date = sorted(rasters, key=name_to_date)
    copy = list(range(len(rasters)))
    midpoint = len(rasters) // 2
    copy[midpoint] = by_date[0]

    add = 1
    left = True
    for idx, raster in enumerate(by_date):
        if idx == 0:
            continue

        if left:
            copy[midpoint - add] = raster
            left = False
        else:
            copy[midpoint + add] = raster
            left = True

            add += 1

    return copy


@jit(nopython=True, parallel=True, nogil=True, fastmath=True, inline="always")
def hood_quantile(values, weights, quant):
    sort_mask = np.argsort(values)
    sorted_data = values[sort_mask]
    sorted_weights = weights[sort_mask]
    cumsum = np.cumsum(sorted_weights)
    intersect = (cumsum - 0.5 * sorted_weights) / cumsum[-1]
    return np.interp(quant, intersect, sorted_data)


@jit(nopython=True, parallel=True, nogil=True, fastmath=True, cache=True)
def s1_collapse(
    arr,
    offsets,
    weights,
    feather_weights,
    quantile=0.5,
    nodata=True,
    nodata_value=-9999.0,
    weighted=True,
):
    x_adj = arr.shape[0] - 1
    y_adj = arr.shape[1] - 1
    z_adj = (arr.shape[2] - 1) // 2

    hood_size = len(offsets)
    if nodata:
        result = np.full(arr.shape[:2], nodata_value, dtype="float32")
    else:
        result = np.zeros(arr.shape[:2], dtype="float32")

    for x in prange(arr.shape[0]):
        for y in range(arr.shape[1]):

            hood_values = np.zeros(hood_size, dtype="float32")
            hood_weights = np.zeros(hood_size, dtype="float32")
            weight_sum = np.array([0.0], dtype="float32")

            for n in range(hood_size):
                offset_x = x + offsets[n][0]
                offset_y = y + offsets[n][1]
                offset_z = offsets[n][2]

                outside = False

                if offset_z < -z_adj:
                    offset_z = -z_adj
                    outside = True
                elif offset_z > z_adj:
                    offset_z = z_adj
                    outside = True

                if offset_x < 0:
                    offset_x = 0
                    outside = True
                elif offset_x > x_adj:
                    offset_x = x_adj
                    outside = True

                if offset_y < 0:
                    offset_y = 0
                    outside = True
                elif offset_y > y_adj:
                    offset_y = y_adj
                    outside = True

                value = arr[offset_x, offset_y, offset_z]

                if outside or (nodata and value == nodata_value):
                    continue

                hood_values[n] = value
                weight = weights[n] * feather_weights[offset_x, offset_y, offset_z]

                hood_weights[n] = weight
                weight_sum[0] += weight

            hood_weights = np.divide(hood_weights, weight_sum[0])

            if weight_sum[0] > 0:
                if weighted:
                    result[x, y] = hood_quantile(hood_values, hood_weights, quantile)
                else:
                    result[x, y] = np.median(hood_values[np.nonzero(hood_weights)])

    return result


def process_aligned(
    aligned_rasters,
    out_path,
    folder_tmp,
    chunks,
    master_raster,
    nodata_value,
    feather_weights=None,
):
    kernel_size = 3
    chunk_offset = kernel_size // 2

    _kernel, offsets, weights = create_kernel(
        (kernel_size, kernel_size, len(aligned_rasters)),
        distance_calc=False,  # "gaussian"
        sigma=1,
        spherical=True,
        radius_method="ellipsoid",
        offsets=True,
        edge_weights=True,
        normalised=True,
        remove_zero_weights=True,
    )

    arr_aligned = raster_to_array(aligned_rasters)

    if feather_weights is not None:
        feather_weights_arr = raster_to_array(feather_weights)

    if not rasters_are_aligned(aligned_rasters):
        raise Exception("Rasters not aligned")

    if chunks > 1:
        chunks_list = []
        print("Chunking rasters")

        uids = uuid4()

        for chunk in range(chunks):
            print(f"Chunk {chunk + 1} of {chunks}")

            cut_start = False
            cut_end = False

            if chunk == 0:
                chunk_start = 0
            else:
                chunk_start = (chunk * (arr_aligned.shape[0] // chunks)) - chunk_offset
                cut_start = True

            if chunk == chunks - 1:
                chunk_end = arr_aligned.shape[0]
            else:
                chunk_end = (
                    (chunk + 1) * (arr_aligned.shape[0] // chunks)
                ) + chunk_offset
                cut_end = True

            arr_chunk = arr_aligned[chunk_start:chunk_end]

            if feather_weights is not None:
                weights_chunk = feather_weights_arr[chunk_start:chunk_end]
            else:
                weights_chunk = np.ones_like(arr_chunk)

            print("    Collapsing...")
            arr_collapsed = s1_collapse(
                arr_chunk,
                offsets,
                weights,
                weights_chunk,
                weighted=True,
                nodata_value=nodata_value,
                nodata=True,
            )

            offset_start = chunk_offset if cut_start else 0
            offset_end = (
                arr_collapsed.shape[0] - chunk_offset
                if cut_end
                else arr_collapsed.shape[0]
            )

            chunk_path = folder_tmp + f"{uids}_chunk_{chunk}.npy"
            chunks_list.append(chunk_path)

            np.save(chunk_path, arr_collapsed[offset_start:offset_end])

            arr_chunk = None
            arr_collapsed = None

        print("Merging Chunks")
        arr_aligned = None

        merged = []
        for chunk in chunks_list:
            merged.append(np.load(chunk))

        merged = np.concatenate(merged)
        merged = np.ma.masked_array(merged, mask=merged == nodata_value)
        merged.fill_value = nodata_value

        print("Writing raster.")
        array_to_raster(
            merged,
            master_raster,
            out_path=out_path,
        )

        merged = None
        return out_path

    if feather_weights is not None:
        weights_borders = feather_weights
    else:
        weights_borders = np.ones_like(arr_aligned)

    print("Collapsing rasters")
    arr_collapsed = s1_collapse(
        arr_aligned,
        offsets,
        weights,
        weights_borders,
        weighted=True,
        nodata_value=nodata_value,
        nodata=True,
    )

    arr_collapsed = np.ma.masked_array(
        arr_collapsed, mask=arr_collapsed == nodata_value
    )
    arr_collapsed.fill_value = nodata_value

    arr_aligned = None

    print("Writing raster.")
    array_to_raster(
        arr_collapsed,
        master_raster,
        out_path=out_path,
    )

    arr_collapsed = None

    return out_path


def mosaic_s1(
    vv_or_vv_paths,
    out_path,
    folder_tmp,
    master_raster,
    nodata_value=-9999.0,
    chunks=1,
    feather_borders=True,
    feather_distance=5000,
    skip_completed=False,
):
    if not isinstance(vv_or_vv_paths, list):
        raise Exception("vv_or_vv_paths must be a list")

    if len(vv_or_vv_paths) < 2:
        raise Exception("vv_or_vv_paths must contain more than one file")

    preprocessed = vv_or_vv_paths
    clipped = []

    for idx, img in enumerate(preprocessed):
        progress(idx, len(preprocessed), "Clipping Rasters")
        name = os.path.splitext(os.path.basename(img))[0] + "_clipped.tif"
        out_name_clip = folder_tmp + name

        if skip_completed and os.path.exists(out_name_clip):
            clipped_raster = folder_tmp + name
        else:
            reprojected = reproject_raster(
                img,
                master_raster,
                copy_if_already_correct=False,
            )

            if not rasters_intersect(reprojected, master_raster):
                print("")
                print(f"{img} does not intersect {master_raster}, continuing\n")
                progress(idx + 1, len(preprocessed), "Clipping Rasters")
                gdal.Unlink(reprojected)
                continue

            clipped_raster = clip_raster(
                reprojected,
                master_raster,
                out_path=folder_tmp + name,
                postfix="",
                adjust_bbox=True,
                all_touch=False,
            )

        clipped.append(clipped_raster)

        gdal.Unlink(reprojected)
        progress(idx + 1, len(preprocessed), "Clipping Rasters")

    arr_aligned_rasters_feather = None

    print("Aligning VV rasters to master")

    arr_aligned_rasters = align_rasters(
        clipped,
        out_path=folder_tmp,
        master=master_raster,
        skip_existing=skip_completed,
    )

    if feather_borders:
        print("Feathering VV rasters")
        arr_aligned_rasters_feather = calc_proximity(
            arr_aligned_rasters,
            target_value=-9999.0,
            out_path=folder_tmp,
            max_dist=feather_distance,
            invert=False,
            weighted=True,
            add_border=True,
            skip_existing=skip_completed,
        )

    print("Processing VV")
    outpath = process_aligned(
        arr_aligned_rasters,
        out_path,
        folder_tmp,
        chunks,
        master_raster,
        nodata_value,
        feather_weights=arr_aligned_rasters_feather,
    )

    return outpath


from glob import glob


folder = "C:/Users/caspe/Desktop/test_area/tmp2/"
# master = folder + "test_10m_v3.tif"
master = "C:/Users/caspe/Desktop/test_area/S2_mosaic/B04_10m.tif"
vv_paths = sort_rasters(glob(folder + "*Gamma0_VV*.tif"))
vh_paths = sort_rasters(glob(folder + "*Gamma0_VH*.tif"))

out_dir = folder + "out/"
tmp_dir = folder + "tmp/"

# mosaic_s1(
#     vv_paths,
#     out_dir + "VV_10m.tif",
#     tmp_dir,
#     master,
#     chunks=5,
#     skip_completed=True,
# )

mosaic_s1(
    vh_paths,
    out_dir + "VH_10m.tif",
    tmp_dir,
    master,
    chunks=5,
    skip_completed=True,
)
