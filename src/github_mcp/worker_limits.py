"""Fail closed if the worker cannot enforce its process memory budget."""

import sys

MEMORY_BYTES = 1_073_741_824
_JOB = None


def limit_memory():
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
        return
    import ctypes as c

    class Basic(c.Structure):
        _fields_ = [
            ("user_time", c.c_longlong),
            ("job_time", c.c_longlong),
            ("flags", c.c_uint32),
            ("min_ws", c.c_size_t),
            ("max_ws", c.c_size_t),
            ("processes", c.c_uint32),
            ("affinity", c.c_size_t),
            ("priority", c.c_uint32),
            ("scheduling", c.c_uint32),
        ]

    class Extended(c.Structure):
        _fields_ = [
            ("basic", Basic),
            ("io", c.c_ulonglong * 6),
            ("process_memory", c.c_size_t),
            ("job_memory", c.c_size_t),
            ("peak_process", c.c_size_t),
            ("peak_job", c.c_size_t),
        ]

    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [c.c_void_p, c.c_wchar_p]
    kernel.CreateJobObjectW.restype = c.c_void_p
    kernel.SetInformationJobObject.argtypes = [
        c.c_void_p,
        c.c_int,
        c.c_void_p,
        c.c_uint32,
    ]
    kernel.SetInformationJobObject.restype = c.c_int
    kernel.AssignProcessToJobObject.argtypes = [c.c_void_p, c.c_void_p]
    kernel.AssignProcessToJobObject.restype = c.c_int
    kernel.GetCurrentProcess.restype = c.c_void_p
    handle = kernel.CreateJobObjectW(None, None)
    info = Extended()
    info.basic.flags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    info.process_memory = MEMORY_BYTES
    if (
        not handle
        or not kernel.SetInformationJobObject(handle, 9, c.byref(info), c.sizeof(info))
        or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess())
    ):
        raise OSError("Unable to enforce worker memory limit")
    global _JOB
    _JOB = handle  # Keep the private job alive until process exit; the OS closes it.
