# Original:
    assert not remaining_files, (
        f"Temporary files remained after cleanup: {[f.name for f in remaining_files]}"
    )

# Fixed:
    assert not remaining_files, (
        "Temporary files remained after cleanup: "
        f"{[f.name for f in remaining_files]}"
    )
