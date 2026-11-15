"""CPU-safe package for the week 7 scaled serving rig.

Modules in this package are deliberately split:
- contract, policy, config, datasets, workload, stats, grading, analysis: pure CPU.
- controller, server, client, runner: GPU/runtime-facing; import vLLM only inside
  their entry points so CPU tests never load torch or vLLM.
"""
__version__ = "0.1.0-p0"
