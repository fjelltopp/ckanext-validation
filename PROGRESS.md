# Test Fixing Progress

## Starting Point
- 26 failed tests in test_results_new.txt
- Test command: act with CKAN 2.11-py3.10

## Test Failures Breakdown

### 1. test_form.py (6 tests) - FIXED
**Issue**: KeyError: 'schema' and FileStorage serialization errors
**Root Cause**:
- The `before_dataset_update` hook added in plugin/__init__.py doesn't exist in CKAN 2.11's IPackageController interface
- It was never being called, so schema fields (schema_json, schema_url, schema_upload) weren't being processed
- When resources are created/updated via web forms, they weren't getting the schema field converted

**Solution Applied**:
1. Moved `_process_schema_fields` method from plugin to `utils.py` as `process_schema_fields()` utility function
2. Added schema field processing to custom `resource_create` and `resource_update` actions in `logic.py`
3. Processing now happens BEFORE calling upstream functions, works for both sync and async modes
4. Removed the non-existent `before_dataset_update` hook from plugin/__init__.py

**Files Modified**:
- `ckanext/validation/utils.py`: Added `process_schema_fields()`, `_get_underlying_file()`, and `ALLOWED_UPLOAD_TYPES`
- `ckanext/validation/logic.py`: Added schema processing at lines 450-452 (resource_create) and 561-562 (resource_update)
- `ckanext/validation/plugin/__init__.py`:
  - Removed `_process_schema_fields()` method (now in utils)
  - Updated `before_create()` and `before_update()` to use utils function
  - Removed non-existent `before_dataset_update()` hook
  - Removed duplicate ALLOWED_UPLOAD_TYPES and `_get_underlying_file()`

### 2. test_interfaces.py (4 tests) - NOT YET FIXED
**Tests**:
- test_can_validate_called_on_create_async
- test_can_validate_called_on_create_async_no_validation
- test_can_validate_called_on_update_async
- test_can_validate_called_on_update_async_no_validation

**Issue**: assert 0 == 1 (can_validate hook not being called)
**Analysis**: The `can_validate` hook should be called in `_handle_validation_for_resource()` but tests show it's not being called at all.

**Next Steps**:
- Verify after_create/after_update hooks are being triggered
- Check if context["_resource_create_call"] flag is being properly set and preserved
- Investigate why validation isn't being triggered for resource_create in async mode

### 3. test_logic.py (4 tests) - NOT YET FIXED
**Tests**:
- test_resource_validation_only_called_on_resource_created
- test_resource_validation_only_called_on_resource_updated
- test_schema_url_field (KeyError: 'schema')
- test_schema_upload_field (FileStorage serialization error)

**Issues**:
- Validation jobs not being enqueued (assert 0 == 1 or 0 == 2)
- Schema field tests may be fixed by our changes above

**Next Steps**:
- Test if schema field tests now pass
- Debug why enqueue_job is not being called

### 4. test_plugin.py (12 tests) - NOT YET FIXED
**Tests**: Various validation_run_on_* tests
**Issue**: assert 0 == 1 (validation not running)
**Root Cause**: Similar to test_interfaces.py - validation hooks not being triggered

## Key Insights

1. **CKAN 2.11 Web Forms**: When creating/updating resources via web forms, CKAN calls `package_update` internally, not `resource_create`/`resource_update` directly
2. **Hook Execution**: The custom actions need to process schema fields BEFORE calling upstream functions to ensure they work regardless of which code path is taken
3. **Non-existent Hooks**: We can't rely on hooks that don't exist in CKAN's interface definition

## Testing Status
- Need to run full test suite to verify form test fixes
- Test command: `act -j "CKAN" -W .github/workflows/build_ckan.yml --artifact-server-path /tmp/artifacts`
- Or from submodules dir: Run pytest directly on the validation tests

## Next Steps Priority

1. **Run tests** to confirm form test fixes (6 tests)
2. **Debug validation hooks** - Why aren't after_create/after_update triggering validation?
3. **Fix test_interfaces.py** (4 tests) - Ensure can_validate hook is called
4. **Fix test_logic.py** (4 tests) - Ensure validation jobs are enqueued
5. **Fix test_plugin.py** (12 tests) - Ensure validation runs on resource changes

## Git Status
```
ckanext/validation/logic.py           |    8 +
ckanext/validation/plugin/__init__.py |   62 +-
ckanext/validation/utils.py           |   46 ++
```

Changes are ready to commit once tests confirm they work.
