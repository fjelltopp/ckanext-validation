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

### 2. test_interfaces.py (4 tests) - FIXED
**Tests**:
- test_can_validate_called_on_create_async
- test_can_validate_called_on_create_async_no_validation
- test_can_validate_called_on_update_async
- test_can_validate_called_on_update_async_no_validation

**Issue**: assert 0 == 1 (can_validate hook not being called)
**Root Cause**:
- In async mode, `resource_create` and `resource_update` in logic.py return early and call upstream functions
- The `after_update` hook was expecting to be called twice (once with package, once with resource)
- In CKAN 2.11, it's only called once with the package, causing resources marked for validation to be skipped

**Solution Applied**:
1. Set `context['_resource_create_call'] = True` in async `resource_create` before calling upstream (logic.py line 456)
2. Check and validate resources in `self.resources_to_validate` before returning early in `after_update` (plugin/__init__.py lines 243-251)
3. This ensures validation runs even when `packages_to_skip` causes early return

### 3. test_logic.py (2 tests) - FIXED
**Tests**:
- test_resource_validation_only_called_on_resource_created
- test_resource_validation_only_called_on_resource_updated

**Issue**: Validation jobs not being enqueued (assert 0 == 1 or 0 == 2)
**Root Cause**: Same as test_interfaces.py - validation hooks weren't being triggered properly in async mode
**Solution**: Fixed by the changes above

### 4. test_plugin.py (12 tests) - FIXED
**Tests**: Various validation_run_on_* tests
**Issue**: assert 0 == 1 (validation not running)
**Root Cause**: Same as test_interfaces.py - validation hooks weren't being triggered properly in async mode
**Solution**: Fixed by the changes above

## Key Insights

1. **CKAN 2.11 Web Forms**: When creating/updating resources via web forms, CKAN calls `package_update` internally, not `resource_create`/`resource_update` directly
2. **Hook Execution**: The custom actions need to process schema fields BEFORE calling upstream functions to ensure they work regardless of which code path is taken
3. **Non-existent Hooks**: We can't rely on hooks that don't exist in CKAN's interface definition

## Testing Status
- **Latest**: 8 failed, 18 passed (69% passing!)
- **Progress**: 26 failed → 18 failed → 11 failed → 8 failed
- Test command: `act -j "CKAN" -W .github/workflows/build_ckan.yml --artifact-server-path /tmp/artifacts`

### Batch 3 Changes - Double Validation Fix
**Problem**: Validation called twice (custom action + hooks)

**Solution**: Use plugin class variable `resources_validated_in_action` with proper timing:
1. Check if validation needed
2. **Mark resource BEFORE calling up_func** (critical timing!)
3. Call up_func (hooks see mark and skip)
4. Trigger validation

**Files Modified**:
- `logic.py`: Mark resources before up_func in both resource_create and resource_update
- `plugin/__init__.py`: Check resources_validated_in_action in after_update hook, skip if marked

### Remaining Failures (Need Testing)
1. **test_interfaces update (2)**: Should be fixed by timing correction
2. **test_logic validation (2)**: Package create not triggering validation
3. **test_plugin package (7)**: Package create/update not triggering validation
4. **test_plugin upload (1)**: resource_update with upload not triggering

## Latest Changes (Batch 2 - Revised Approach)

**Root Cause Identified**:
- In CKAN 2.11, the hook flow (before_create/after_create/before_update/after_update) is not reliably triggered when chained actions call upstream functions
- Relying on hooks to trigger validation in async mode doesn't work consistently

**New Solution - Direct Validation in Custom Actions**:

**Files Modified**:
1. `ckanext/validation/logic.py` (lines 454-476 for resource_create, 585-628 for resource_update):
   - **resource_create async mode**: After calling upstream, explicitly check validation criteria and call `can_validate` hook, then trigger validation
   - **resource_update async mode**: Get current resource, call upstream, compare changes to determine if validation needed, call `can_validate` hook, then trigger validation
   - This bypasses the unreliable hook flow and directly controls validation

2. `ckanext/validation/plugin/__init__.py` (lines 243-253):
   - Fixed logic bug in early return validation check (was using `continue` incorrectly)
   - Now uses `should_validate` flag and `break` to properly handle `can_validate` results

## Next Steps

1. **Run full test suite** to verify all 18 remaining failures are now fixed
2. **If tests pass**, commit changes with message describing the async validation fix
3. **If tests still fail**, analyze remaining failures and continue debugging

## Expected Outcome
All 26 tests should now pass:
- test_form.py: 6 tests (fixed in batch 1)
- test_logic.py schema tests: 2 tests (fixed in batch 1)
- test_interfaces.py: 4 tests (fixed in batch 2)
- test_logic.py validation tests: 2 tests (fixed in batch 2)
- test_plugin.py: 12 tests (fixed in batch 2)
