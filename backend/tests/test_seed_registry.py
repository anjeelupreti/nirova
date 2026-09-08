"""That the seed registry matches what is actually on disk.

Deliberately its own module with **no database marks**. The seed suite is the
slow half and is skipped by `-m "not seeds"`; this check costs a directory
listing and is exactly the kind of thing that must run every time.
"""

from apps.tenancy.seeding import CONTROL_PLANE_SEEDS, TENANT_SEEDS

def test_every_seed_command_is_in_the_order():
    """No demo seed may exist without being listed in `TENANT_SEEDS`.

    `seed_hr_demo` was written, committed, documented in the README, and then
    left out of this module's list. Nothing ran it for months. When the
    container finally did, it raised `NameError` on line 356 -- a bug that had
    been sitting in committed code the whole time, in a branch no execution
    had ever reached.

    That is the same lesson this project keeps relearning: **the bugs are in
    the code nobody has ever executed.** A list of things to test that is
    maintained by hand will eventually disagree with what exists, and it will
    disagree silently. This asks the filesystem instead.

    `seed_catalog` and `seed_demo` are excluded because they are control-plane
    seeds -- they build the tenant these run inside, so they cannot run in it.
    """
    import pathlib

    import apps

    root = pathlib.Path(apps.__file__).parent
    on_disk = {
        path.stem
        for path in root.glob("*/management/commands/seed_*.py")
        if path.stem not in set(CONTROL_PLANE_SEEDS)
    }
    listed = set(TENANT_SEEDS)

    missing = sorted(on_disk - listed)
    assert not missing, (
        "these seed commands exist but no test or bootstrap ever runs them, "
        "so nothing has executed their code: " + ", ".join(missing)
    )

    phantom = sorted(listed - on_disk)
    assert not phantom, (
        "TENANT_SEEDS names commands that do not exist: " + ", ".join(phantom)
    )
