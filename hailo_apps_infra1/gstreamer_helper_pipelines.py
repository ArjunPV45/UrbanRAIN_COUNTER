import os
import subprocess
import json


def detect_rtsp_codec(rtsp_url):
    """Detect video codec using ffprobe"""
    cmd = [
        'ffprobe',
        '-v', 'quiet',
        '-print_format', 'json',
        '-show_streams',
        '-show_format',
        '-rtsp_transport', 'tcp',
        rtsp_url
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            video_streams = [s for s in data.get('streams', []) if s.get('codec_type') == 'video']
            if video_streams:
                codec = video_streams[0].get('codec_name', '').lower()
                return codec
    except Exception as e:
        print(f"[WARN] ffprobe failed for {rtsp_url}: {e}")
    return None


def get_source_type(input_source):
    if input_source.startswith("/dev/video"):
        return 'usb'
    elif input_source.startswith("rpi"):
        return 'rpi'
    elif input_source.startswith("libcamera"):
        return 'libcamera'
    elif input_source.startswith('0x'):
        return 'ximage'
    elif input_source.startswith("rtsp"):
        return 'rtsp'
    else:
        return 'file'


def QUEUE(name, max_size_buffers=3, max_size_bytes=0, max_size_time=0, leaky='no'):
    return f'queue name={name} leaky={leaky} max-size-buffers={max_size_buffers} max-size-bytes={max_size_bytes} max-size-time={max_size_time} '


def get_camera_resolotion(video_width=640, video_height=640):
    if video_width <= 640 and video_height <= 480:
        return 640, 480
    elif video_width <= 1280 and video_height <= 720:
        return 1280, 720
    elif video_width <= 1920 and video_height <= 1080:
        return 1920, 1080
    else:
        return 3840, 2160


def get_rtsp_codec_pipeline(video_source, name_with_index, codec_type=None):
    codec_type = codec_type.lower() if codec_type else 'h264'
    if codec_type in ['h264', 'avc1']:
        return (
            f"rtspsrc location={video_source} name={name_with_index} latency=200 buffer-mode=1 "
            f"timeout=10000000 drop-on-latency=true is-live=true udp-buffer-size=524288 protocols=udp ! "
            f"rtph264depay ! h264parse ! avdec_h264 ! "
            f"{QUEUE(name=f'{name_with_index}_queue', max_size_buffers=5, leaky='downstream')} ! "
            f"video/x-raw, format=I420 ! "
        )
    elif codec_type in ['hevc', 'h265']:
        return (
            f"rtspsrc location={video_source} name={name_with_index} latency=200 buffer-mode=1 "
            f"timeout=10000000 drop-on-latency=true is-live=true udp-buffer-size=524288 protocols=udp ! "
            f"rtph265depay ! h265parse ! avdec_h265 ! "
            f"{QUEUE(name=f'{name_with_index}_queue', max_size_buffers=5, leaky='downstream')} ! "
            f"video/x-raw, format=I420 ! "
        )
    else:
        print(f"[WARN] Unknown codec '{codec_type}', defaulting to H264.")
        return (
            f"rtspsrc location={video_source} name={name_with_index} latency=200 buffer-mode=1 "
            f"timeout=10000000 drop-on-latency=true is-live=true udp-buffer-size=524288 protocols=udp ! "
            f"rtph264depay ! h264parse ! avdec_h264 ! "
            f"{QUEUE(name=f'{name_with_index}_queue', max_size_buffers=5, leaky='downstream')} ! "
            f"video/x-raw, format=I420 ! "
        )


def SOURCE_PIPELINE(video_source, video_width=640, video_height=640, video_format='RGB', name='source', no_webcam_compression=False, source_index=None):
    source_type = get_source_type(video_source)
    if source_index is not None:
        unique_suffix = f"_{source_index}"
        name_with_index = f"{name}{unique_suffix}"
    else:
        unique_suffix = ""
        name_with_index = name

    if source_type == 'usb':
        if no_webcam_compression:
            source_element = (
                f'v4l2src device={video_source} name={name_with_index} ! '
                f'video/x-raw, format=RGB, width=640, height=480 ! '
                f'videoflip name=videoflip{unique_suffix} video-direction=horiz ! '
            )
        else:
            width, height = get_camera_resolotion(video_width, video_height)
            source_element = (
                f'v4l2src device={video_source} name={name_with_index} ! image/jpeg, framerate=30/1, width={width}, height={height} ! '
                f'{QUEUE(name=f"{name_with_index}_queue_decode")} ! '
                f'decodebin name={name_with_index}_decodebin ! '
                f'videoflip name=videoflip{unique_suffix} video-direction=horiz ! '
            )
    elif source_type == 'rpi':
        source_element = (
            f'appsrc name=app_source{unique_suffix} is-live=true leaky-type=downstream max-buffers=3 ! '
            f'videoflip name=videoflip{unique_suffix} video-direction=horiz ! '
            f'video/x-raw, format={video_format}, width={video_width}, height={video_height} ! '
        )
    elif source_type == "rtsp":
        codec_type = detect_rtsp_codec(video_source)
        print(f"[INFO] Detected codec for {video_source}: {codec_type}")
        source_element = get_rtsp_codec_pipeline(video_source, name_with_index, codec_type)
    elif source_type == 'libcamera':
        source_element = (
            f'libcamerasrc name={name_with_index} ! '
            f'video/x-raw, format={video_format}, width=1536, height=864 ! '
        )
    elif source_type == 'ximage':
        source_element = (
            f'ximagesrc xid={video_source} ! '
            f'{QUEUE(name=f"{name_with_index}queue_scale_")} ! '
            f'videoscale ! '
        )
    else:
        source_element = (
            f"rtspsrc location={video_source} name={name} message-forward=true ! "
            f"rtph264depay !"
            f"queue name=hailo_preprocess_q_0 leaky=no max-size-buffers=5 max-size-bytes=0 max-size-time=0 ! "
            f"decodebin ! queue leaky=downstream max-size-buffers=5 max-size-bytes=0 max-size-time=0 ! "
            f"video/x-raw, format=I420 ! "
        )

    source_pipeline = (
        f'{source_element} '
        f'{QUEUE(name=f"{name_with_index}_scale_q")} ! '
        f'videoscale name={name_with_index}_videoscale n-threads=2 ! '
        f'{QUEUE(name=f"{name_with_index}_convert_q")} ! '
        f'videoconvert n-threads=3 name={name_with_index}_convert qos=false ! '
        f'video/x-raw, pixel-aspect-ratio=1/1, format={video_format}, width={video_width}, height={video_height} '
    )
    return source_pipeline


def INFERENCE_PIPELINE(
    hef_path,
    post_process_so=None,
    batch_size=1,
    config_json=None,
    post_function_name=None,
    additional_params='',
    name='inference',
    # Extra hailonet parameters
    scheduler_timeout_ms=None,
    scheduler_priority=None,
    vdevice_group_id=1,
    multi_process_service=None
):
    """
    Creates a GStreamer pipeline string for inference and post-processing using a user-provided shared object file.
    This pipeline includes videoscale and videoconvert elements to convert the video frame to the required format.
    The format and resolution are automatically negotiated based on the HEF file requirements.

    Args:
        hef_path (str): Path to the HEF file.
        post_process_so (str or None): Path to the post-processing .so file. If None, post-processing is skipped.
        batch_size (int): Batch size for hailonet (default=1).
        config_json (str or None): Config JSON for post-processing (e.g., label mapping).
        post_function_name (str or None): Function name in the .so postprocess.
        additional_params (str): Additional parameters appended to hailonet.
        name (str): Prefix name for pipeline elements (default='inference').

        # Extra hailonet parameters
        Run `gst-inspect-1.0 hailonet` for more information.
        vdevice_group_id (int): hailonet vdevice-group-id. Default=1.
        scheduler_timeout_ms (int or None): hailonet scheduler-timeout-ms. Default=None.
        scheduler_priority (int or None): hailonet scheduler-priority. Default=None.
        multi_process_service (bool or None): hailonet multi-process-service. Default=None.

    Returns:
        str: A string representing the GStreamer pipeline for inference.
    """
    # config & function strings
    config_str = f' config-path={config_json} ' if config_json else ''
    function_name_str = f' function-name={post_function_name} ' if post_function_name else ''
    vdevice_group_id_str = f' vdevice-group-id={vdevice_group_id} '
    multi_process_service_str = f' multi-process-service={str(multi_process_service).lower()} ' if multi_process_service is not None else ''
    scheduler_timeout_ms_str = f' scheduler-timeout-ms={scheduler_timeout_ms} ' if scheduler_timeout_ms is not None else ''
    scheduler_priority_str = f' scheduler-priority={scheduler_priority} ' if scheduler_priority is not None else ''

    hailonet_str = (
        f'hailonet name={name}_hailonet '
        f'hef-path={hef_path} '
        f'batch-size={batch_size} '
        f'{vdevice_group_id_str}'
        f'{multi_process_service_str}'
        f'{scheduler_timeout_ms_str}'
        f'{scheduler_priority_str}'
        f'nms-score-threshold=0.3 nms-iou-threshold=0.45 '
        f'output-format-type=HAILO_FORMAT_TYPE_FLOAT32 '
        f'force-writable=true '
        f'{additional_params} '
    )

    inference_pipeline = (
        f'{QUEUE(name=f"{name}_scale_q")} ! '
        f'videoscale name={name}_videoscale n-threads=2 qos=false ! '
        f'{QUEUE(name=f"{name}_convert_q")} ! '
        f'video/x-raw, pixel-aspect-ratio=1/1 ! '
        f'videoconvert name={name}_videoconvert n-threads=2 ! '
        f'{QUEUE(name=f"{name}_hailonet_q")} ! '
        f'{hailonet_str} ! '
    )

    if post_process_so:
        inference_pipeline += (
            f'{QUEUE(name=f"{name}_hailofilter_q")} ! '
            f'hailofilter name={name}_hailofilter so-path={post_process_so} {config_str} {function_name_str} qos=false ! '
        )

    inference_pipeline += f'{QUEUE(name=f"{name}_output_q")} '

    return inference_pipeline

def INFERENCE_PIPELINE_WRAPPER(inner_pipeline, bypass_max_size_buffers=20, name='inference_wrapper'):
    """
    Creates a GStreamer pipeline string that wraps an inner pipeline with a hailocropper and hailoaggregator.
    This allows to keep the original video resolution and color-space (format) of the input frame.
    The inner pipeline should be able to do the required conversions and rescale the detection to the original frame size.

    Args:
        inner_pipeline (str): The inner pipeline string to be wrapped.
        bypass_max_size_buffers (int, optional): The maximum number of buffers for the bypass queue. Defaults to 20.
        name (str, optional): The prefix name for the pipeline elements. Defaults to 'inference_wrapper'.

    Returns:
        str: A string representing the GStreamer pipeline for the inference wrapper.
    """
    # Get the directory for post-processing shared objects
    tappas_post_process_dir = os.environ.get('TAPPAS_POST_PROC_DIR', '')
    whole_buffer_crop_so = os.path.join(tappas_post_process_dir, 'cropping_algorithms/libwhole_buffer.so')

    # Construct the inference wrapper pipeline string
    inference_wrapper_pipeline = (
        f'{QUEUE(name=f"{name}_input_q")} ! '
        f'hailocropper name={name}_crop so-path={whole_buffer_crop_so} function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true '
        f'hailoaggregator name={name}_agg '
        f'{name}_crop. ! {QUEUE(max_size_buffers=bypass_max_size_buffers, name=f"{name}_bypass_q")} ! {name}_agg.sink_0 '
        f'{name}_crop. ! {inner_pipeline} ! {name}_agg.sink_1 '
        f'{name}_agg. ! {QUEUE(name=f"{name}_output_q")} '
    )

    return inference_wrapper_pipeline

def OVERLAY_PIPELINE(name='hailo_overlay'):
    """
    Creates a GStreamer pipeline string for the hailooverlay element.
    This pipeline is used to draw bounding boxes and labels on the video.

    Args:
        name (str, optional): The prefix name for the pipeline elements. Defaults to 'hailo_overlay'.

    Returns:
        str: A string representing the GStreamer pipeline for the hailooverlay element.
    """
    # Construct the overlay pipeline string
    overlay_pipeline = (
        f'{QUEUE(name=f"{name}_q")} ! '
        f'hailooverlay name={name} '
    )

    return overlay_pipeline

def DISPLAY_PIPELINE(video_sink='autovideosink', sync='true', show_fps='false', name='hailo_display'):
    """
    Creates a GStreamer pipeline string for displaying the video.
    It includes the hailooverlay plugin to draw bounding boxes and labels on the video.

    Args:
        video_sink (str, optional): The video sink element to use. Defaults to 'autovideosink'.
        sync (str, optional): The sync property for the video sink. Defaults to 'true'.
        show_fps (str, optional): Whether to show the FPS on the video sink. Should be 'true' or 'false'. Defaults to 'false'.
        name (str, optional): The prefix name for the pipeline elements. Defaults to 'hailo_display'.

    Returns:
        str: A string representing the GStreamer pipeline for displaying the video.
    """
    # Construct the display pipeline string
    display_pipeline = (
        f'{OVERLAY_PIPELINE(name=f"{name}_overlay")} ! '
        f'{QUEUE(name=f"{name}_videoconvert_q")} ! '
        f'videoconvert name={name}_videoconvert n-threads=2 qos=false ! '
        f'{QUEUE(name=f"{name}_q")} ! '
        f'fpsdisplaysink name={name} video-sink={video_sink} sync={sync} text-overlay={show_fps} signal-fps-measurements=true '
    )

    return display_pipeline

def FILE_SINK_PIPELINE(output_file='output.mkv', name='file_sink', bitrate=5000):
    """
    Creates a GStreamer pipeline string for saving the video to a file in .mkv format.
    It it recommended run ffmpeg to fix the file header after recording.
    example: ffmpeg -i output.mkv -c copy fixed_output.mkv
    Note: If your source is a file, looping will not work with this pipeline.
    Args:
        output_file (str): The path to the output file.
        name (str, optional): The prefix name for the pipeline elements. Defaults to 'file_sink'.
        bitrate (int, optional): The bitrate for the encoder. Defaults to 5000.

    Returns:
        str: A string representing the GStreamer pipeline for saving the video to a file.
    """
    # Construct the file sink pipeline string
    file_sink_pipeline = (
        f'{QUEUE(name=f"{name}_videoconvert_q")} ! '
        f'videoconvert name={name}_videoconvert n-threads=2 qos=false ! '
        f'{QUEUE(name=f"{name}_encoder_q")} ! '
        f'x264enc tune=zerolatency bitrate={bitrate} ! '
        f'matroskamux ! '
        f'filesink location={output_file} '
    )

    return file_sink_pipeline

def USER_CALLBACK_PIPELINE(name='identity_callback'):
    """
    Creates a GStreamer pipeline string for the user callback element.

    Args:
        name (str, optional): The prefix name for the pipeline elements. Defaults to 'identity_callback'.

    Returns:
        str: A string representing the GStreamer pipeline for the user callback element.
    """
    # Construct the user callback pipeline string
    user_callback_pipeline = (
        f'{QUEUE(name=f"{name}_q")} ! '
        f'identity name={name} '
    )

    return user_callback_pipeline

def TRACKER_PIPELINE(class_id, kalman_dist_thr=0.7, iou_thr=0.85, init_iou_thr=0.6, keep_new_frames=3, keep_tracked_frames=45, keep_lost_frames=20, keep_past_metadata=True, qos=False, name='hailo_tracker'):
    """
    Creates a GStreamer pipeline string for the HailoTracker element.
    Args:
        class_id (int): The class ID to track. Default is -1, which tracks across all classes.
        kalman_dist_thr (float, optional): Threshold used in Kalman filter to compare Mahalanobis cost matrix. Closer to 1.0 is looser. Defaults to 0.8.
        iou_thr (float, optional): Threshold used in Kalman filter to compare IOU cost matrix. Closer to 1.0 is looser. Defaults to 0.9.
        init_iou_thr (float, optional): Threshold used in Kalman filter to compare IOU cost matrix of newly found instances. Closer to 1.0 is looser. Defaults to 0.7.
        keep_new_frames (int, optional): Number of frames to keep without a successful match before a 'new' instance is removed from the tracking record. Defaults to 2.
        keep_tracked_frames (int, optional): Number of frames to keep without a successful match before a 'tracked' instance is considered 'lost'. Defaults to 15.
        keep_lost_frames (int, optional): Number of frames to keep without a successful match before a 'lost' instance is removed from the tracking record. Defaults to 2.
        keep_past_metadata (bool, optional): Whether to keep past metadata on tracked objects. Defaults to False.
        qos (bool, optional): Whether to enable QoS. Defaults to False.
        name (str, optional): The prefix name for the pipeline elements. Defaults to 'hailo_tracker'.
    Note:
        For a full list of options and their descriptions, run `gst-inspect-1.0 hailotracker`.
    Returns:
        str: A string representing the GStreamer pipeline for the HailoTracker element.
    """
    # Construct the tracker pipeline string
    tracker_pipeline = (
        f'hailotracker name={name} class-id={class_id} kalman-dist-thr={kalman_dist_thr} iou-thr={iou_thr} init-iou-thr={init_iou_thr} '
        f'keep-new-frames={keep_new_frames} keep-tracked-frames={keep_tracked_frames} keep-lost-frames={keep_lost_frames} keep-past-metadata={keep_past_metadata} qos={qos} ! '
        f'{QUEUE(name=f"{name}_q")} '
    )
    return tracker_pipeline

def CROPPER_PIPELINE(
    inner_pipeline,
    so_path,
    function_name,
    use_letterbox=True,
    no_scaling_bbox=True,
    internal_offset=True,
    resize_method='bilinear',
    bypass_max_size_buffers=20,
    name='cropper_wrapper'
):
    """
    Wraps an inner pipeline with hailocropper and hailoaggregator.
    The cropper will crop detections made by earlier stages in the pipeline.
    Each detection is cropped and sent to the inner pipeline for further processing.
    The aggregator will combine the cropped detections with the original frame.
    Example use case: After face detection pipeline stage, crop the faces and send them to a face recognition pipeline.

    Args:
        inner_pipeline (str): The pipeline string to be wrapped.
        so_path (str): The path to the cropper .so library.
        function_name (str): The function name in the .so library.
        use_letterbox (bool): Whether to preserve aspect ratio. Defaults True.
        no_scaling_bbox (bool): If True, bounding boxes are not scaled. Defaults True.
        internal_offset (bool): If True, uses internal offsets. Defaults True.
        resize_method (str): The resize method. Defaults to 'inter-area'.
        bypass_max_size_buffers (int): For the bypass queue. Defaults to 20.
        name (str): A prefix name for pipeline elements. Defaults 'cropper_wrapper'.

    Returns:
        str: A pipeline string representing hailocropper + aggregator around the inner_pipeline.
    """
    return (
        f'{QUEUE(name=f"{name}_input_q")} ! '
        f'hailocropper name={name}_cropper '
        f'so-path={so_path} '
        f'function-name={function_name} '
        f'use-letterbox={str(use_letterbox).lower()} '
        f'no-scaling-bbox={str(no_scaling_bbox).lower()} '
        f'internal-offset={str(internal_offset).lower()} '
        f'resize-method={resize_method} '
        f'hailoaggregator name={name}_agg '
        # bypass
        f'{name}_cropper. ! '
        f'{QUEUE(name=f"{name}_bypass_q", max_size_buffers=bypass_max_size_buffers)} ! {name}_agg.sink_0 '
        # pipeline for the actual inference
        f'{name}_cropper. ! {inner_pipeline} ! {name}_agg.sink_1 '
        # aggregator output
        f'{name}_agg. ! {QUEUE(name=f"{name}_output_q")} '
    )

def CROP_PIPELINE(so_path, function_name="crop_person_by_id", config_json=None, name="cropper", output_path="/tmp/crop_%05d.jpg"):
    config_str = f' config-path={config_json} ' if config_json else ''
    return (
        f'{QUEUE(name=f"{name}_q")} ! '
        f'hailofilter name={name} so-path={so_path} function-name={function_name}{config_str} qos=false ! '
        f'jpegenc ! multifilesink location={output_path} '
    ) 

