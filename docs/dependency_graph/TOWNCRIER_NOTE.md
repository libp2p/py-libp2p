# Towncrier Compatibility Note

## ✅ No Conflicts

Our dependency graph files are **completely separate** from towncrier's validation:

- **Towncrier validates**: `newsfragments/` directory only
- **Our files are in**: `docs/dependency_graph/` directory
- **Result**: No conflicts or validation issues

## Towncrier Configuration

Towncrier is configured in `pyproject.toml`:

- `directory = "newsfragments"` - Only checks this directory
- Validates files matching pattern: `<ISSUE>.<TYPE>.rst`
- Our `.md` files in `docs/dependency_graph/` are not checked

## Validation Script

The `newsfragments/validate_files.py` script:

- Only checks files in `newsfragments/` directory
- Validates file extensions (`.breaking.rst`, `.feature.rst`, etc.)
- Does not scan `docs/` directory

## Conclusion

✅ **Safe to commit** - Towncrier will not complain about our structure.
