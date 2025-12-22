# SD WebUI Forge Task Scheduler - Installation Script
# This extension uses only Python standard library modules (sqlite3, uuid, json, threading)
# No additional pip packages required

try:
    import launch
    skip_install = launch.args.skip_install
except Exception:
    skip_install = False

if not skip_install:
    # Currently no external dependencies needed
    # All required modules are part of Python standard library:
    # - sqlite3: Database storage
    # - uuid: Task ID generation
    # - json: Parameter serialization
    # - threading: Background execution
    # - dataclasses: Data models
    pass
