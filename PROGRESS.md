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

### Batch 4 Changes - Package Create/Update Fix (IN PROGRESS)
**Problem**: Validation not triggered when creating datasets with resources

**Root Cause Analysis**:
- Resources in data_dict passed to after_create don't have IDs yet
- When `factories.Dataset(resources=[...])` is called, it triggers `package_create` which calls `after_create` hook
- Tests expect validation to be triggered once for each resource with supported format

**Attempts Made**:

1. **Attempt 1**: Use package_show to fetch full package
   - **Result**: Still 8 failed (no improvement)
   - **Issue**: May be introducing unnecessary API call overhead

2. **Attempt 2**: Get resources from context['package'].resources (model objects)
   - **Result**: Still 8 failed (no improvement)
   - **Rationale**: Model objects should have complete resource data including IDs
   - **Status**: Need to add debug logging to understand what's happening

**Current Investigation**:
- Added debug logging to after_create hook in plugin/__init__.py (lines 137-179):
  - Log whether after_create is being called
  - Log whether it's identifying as a dataset
  - Log whether context['package'] exists and has resources
  - Log resource IDs and validation status
  - Log when resources are skipped vs validated
- Need to run tests with debug logging to understand the flow

### Remaining 8 Failures
All related to package create/update with resources:

**test_logic.py (2 tests)**:
- test_resource_validation_only_called_on_resource_created
- test_resource_validation_only_called_on_resource_updated

**test_plugin.py - TestPackageControllerHooksCreate (3 tests)**:
- test_validation_run_with_upload
- test_validation_run_with_url
- test_validation_run_only_supported_formats

**test_plugin.py - TestPackageControllerHooksUpdate (3 tests)**:
- test_validation_runs_with_url
- test_validation_runs_with_upload
- test_validation_run_only_supported_formats

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

## Next Steps (Tomorrow)

1. **Run tests with debug logging** to understand after_create flow:
   ```bash
   act -j "test" -W .github/workflows/test.yml --artifact-server-path /tmp/artifacts
   ```
   - Check if after_create is being called
   - Verify it's identifying as dataset
   - See if context['package'] exists
   - Check if resources have IDs
   - Understand why validation isn't being triggered

2. **Analyze debug output** to identify the actual issue

3. **Possible hypotheses to investigate**:
   - after_create might not be called at all for package_create
   - context['package'] might not exist or might not have resources attribute
   - Resources might be getting marked as validated incorrectly
   - _handle_validation_for_resource might be returning early

4. **Alternative approaches if current approach doesn't work**:
   - Check if we need to override package_create action instead of relying on hooks
   - Investigate if there's a different hook that's more reliable for package creation
   - Consider if the issue is with before_create instead of after_create

### Batch 5 Changes - IPackageController Hook Implementation (MAJOR FIX)
**Problem**: Using wrong interface hooks - after_create/after_update are IResourceController hooks, not IPackageController hooks

**Root Cause**:
- `after_create` and `after_update` are for IResourceController (individual resource operations)
- For package operations, we need IPackageController hooks: `after_dataset_create` and `after_dataset_update`
- When `factories.Dataset(resources=[...])` is called, it triggers IPackageController hooks, not IResourceController hooks

**Solution Applied**:
1. **Added `after_dataset_create`** (IPackageController hook):
   - Called when packages/datasets are created with resources
   - Uses resources from data_dict (which have IDs after creation)
   - Added re-entrant call protection with `_in_dataset_create_validation` flag
   - Wrapped in try-finally for cleanup

2. **Added `after_dataset_update`** (IPackageController hook):
   - Called when packages/datasets are updated
   - Handles validation for all resources in the package
   - Added re-entrant call protection with `_in_dataset_update_validation` flag
   - Wrapped in try-finally for cleanup

3. **Fixed circular validation loop**:
   - Added `_validation_performed: True` to patch_context in resource_validation_run (logic.py:139)
   - This prevents infinite loop: validation → resource_patch → package_update → after_dataset_update → validation...

4. **Simplified IResourceController hooks**:
   - `after_create`: Now just passes (individual resource creation handled elsewhere)
   - `after_update`: Simplified to only handle individual resource updates

**Files Modified**:
- `ckanext/validation/plugin/__init__.py`:
  - Added `after_dataset_create` method (lines 139-170)
  - Added `after_dataset_update` method (lines 281-356)
  - Simplified `after_create` and `after_update` for IResourceController
- `ckanext/validation/logic.py`:
  - Added `_validation_performed` flag to patch_context (line 139)

**Results**: 6 out of 8 tests now passing! (75% → 92%)

### Batch 6 Changes - Fix Double/Triple Validation (1 of 2 tests fixed)
**Problem**: Validation being called multiple times instead of once per operation

**Root Causes**:
- **test_resource_validation_only_called_on_resource_created**: Expected 1 call, got 2
  - Custom resource_create action triggered validation
  - after_dataset_update also triggered validation for the same resource
- **test_resource_validation_only_called_on_resource_updated**: Expected 1 call, got 3
  - Custom resource_update action triggered validation
  - after_update (resource hook) triggered validation
  - after_dataset_update (via packages_to_skip) also tried to validate

**Solutions Applied**:
1. **Fix for resource_create** (plugin/__init__.py lines 333-336):
   - When `_resource_create_call` flag is set, after_dataset_update just returns
   - Validation already handled by resource_create action, no duplication
   - Result: test_resource_validation_only_called_on_resource_created now PASSES ✅

2. **Partial fix for resource_update** (plugin/__init__.py lines 271-275):
   - Added check for resources_validated_in_action in after_update
   - Skips validation if already handled by custom resource_update action
   - Cleans up both resources_validated_in_action and resources_to_validate
   - Result: Still 3 calls instead of 1 (needs further investigation)

**Files Modified**:
- `ckanext/validation/plugin/__init__.py`:
  - Modified after_dataset_update to skip validation when _resource_create_call is set
  - Modified after_update to check resources_validated_in_action

**Results**: 1 of 2 tests now passing! (92% → 96%)

### Batch 7 Changes - Fix Resource Update Triple Validation (FINAL FIX - ALL TESTS PASSING!) ✅
**Problem**: test_resource_validation_only_called_on_resource_updated getting 3 validation calls instead of 1

**Root Cause Investigation**:
Through debug logging, discovered that:
1. Custom resource_update action triggered validation (expected - 1 call)
2. after_dataset_update triggered validation for resource_2 (the OTHER resource in the package - NOT expected - 1 call)
3. Total: 2 calls detected, but test showed 3

Further investigation revealed the real issue:
- When custom resource_update calls `up_func(context, data_dict)`, it bypasses CKAN's action framework
- This means hooks like `before_update` are NOT called automatically
- `before_update` is responsible for setting `packages_to_skip[package_id] = True`
- Without this flag, `after_dataset_update` falls through to the "actual package_update" path
- This path validates ALL resources in the package, not just the one being updated

**Solution Applied**:
In `resource_update` action (logic.py lines 652-658):
- When marking resource as validated, also manually set `packages_to_skip[package_id] = True`
- This ensures `after_dataset_update` enters the packages_to_skip block
- In that block, resources are only validated if they're in `resources_to_validate`
- Other resources in the package are skipped

In `after_dataset_update` (plugin/__init__.py lines 355-358):
- Added check for `resources_validated_in_action` in the "actual package_update" path
- This provides a safety net in case packages_to_skip isn't set properly

**Files Modified**:
- `ckanext/validation/logic.py`:
  - Lines 652-658: Set packages_to_skip when marking resource as validated
- `ckanext/validation/plugin/__init__.py`:
  - Lines 355-358: Added resources_validated_in_action check in package_update path

**Results**: ALL TESTS PASSING! (96% → 100%) 🎉

## Final Status Summary
- **Total tests**: 26
- **Passing**: 26 (100%)
- **Failing**: 0 (0%)
- **Batches completed**: 7 (schema fields, async validation in actions, double validation fix, package create/update validation, IPackageController hooks, resource_create double validation fix, resource_update triple validation fix)
- **Status**: COMPLETE ✅
