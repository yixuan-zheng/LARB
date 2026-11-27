"""Engine-process cut-target override for the P3C 6k arm.

The frozen week 7 server hard-codes ``larb_scaled.controller:PressureProcessor``
and the vLLM engine core is a separate process, so patching ``CUT_TARGET`` in
``server_entry`` only changes the HTTP frontend.  ``sitecustomize`` is imported
at interpreter startup in every process that has this directory on
``PYTHONPATH``; when the runner sets ``LARB_CUT_TARGET``, patch the controller
module in the engine core as well.  Without the variable this file is inert.
"""
import os

_target = os.environ.get("LARB_CUT_TARGET")
if _target:
    try:
        from larb_scaled import controller
        controller.CUT_TARGET = int(_target)
    except Exception:
        # CPU/analysis environments do not have vLLM; the server/engine process
        # does, and is the only place this patch matters.
        pass
