"""True native Windows ACL observations in explicitly disposable roots only."""
import json
import sys
from unittest.mock import patch

import pytest

from core import generation_windows_protected_storage as w


@pytest.fixture
def native_scope(tmp_path):
    if sys.platform != "win32":
        pytest.skip("Windows native characterization only")
    pytest.importorskip("win32security")
    api = w._api()
    # Create a fresh disposable scope atomically secured by the real native API.
    # No existing Project/asset or user directory ACL is changed.
    scope = tmp_path / "owner-only-scope"
    api[2].CreateDirectory(str(scope), w._security_attributes(api, w._current_user(api)))
    return scope, api


@pytest.fixture
def native_root(native_scope):
    scope, api = native_scope
    root = w.WindowsProtectedRootCharacterization.provision_journal_for_characterization(
        str(scope), characterization=True, disposable_opt_in=True)
    try:
        yield scope, api, root
    finally:
        root.close()


def assert_no_authority(view):
    assert not any(view[key] for key in ("execution_available", "protected_storage_available",
        "recovery_execution_allowed", "attachment_allowed", "publication_allowed",
        "project_save_allowed", "cleanup_allowed", "power_loss_guarantee",
        "same_user_process_authentication"))
    assert view["authorship"] == "unverified" and view["current_authorization"] == "absent"
    assert view["directory_durability"] == "unsupported" and view["integrity"] == "not_inspected"


@pytest.fixture(params=w.PURPOSES)
def native_nested_path(native_scope, request):
    scope, api = native_scope
    _, c, f, _, _, _ = api
    user = w._current_user(api)
    first = scope / "first"
    second = first / "second"
    for directory in (first, second):
        f.CreateDirectory(str(directory), w._security_attributes(api, user))
    target = second / ("project.json" if request.param == "selected_project_json" else "target")
    if request.param == "selected_project_json":
        handle = f.CreateFile(str(target), c.GENERIC_WRITE, c.FILE_SHARE_READ,
            w._security_attributes(api, user), c.CREATE_NEW, c.FILE_ATTRIBUTE_NORMAL, None)
        try:
            f.WriteFile(handle, b'{"disposable":true}')
        finally:
            handle.Close()
    else:
        f.CreateDirectory(str(target), w._security_attributes(api, user))
    return scope, api, (first, second), target, request.param


def native_descriptors(api, paths):
    security = api[3]
    information = security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION
    return tuple(security.ConvertSecurityDescriptorToStringSecurityDescriptor(
        security.GetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT, information),
        security.SDDL_REVISION_1, information) for path in paths)


def mutate_disposable_acl(path, api, mutation):
    # Only disposable fixtures are mutated; the production inspector is read-only.
    _, c, f, s, n, _ = api
    handle = f.CreateFile(str(path), c.READ_CONTROL | c.WRITE_DAC,
        c.FILE_SHARE_READ | c.FILE_SHARE_WRITE, None, c.OPEN_EXISTING,
        c.FILE_FLAG_BACKUP_SEMANTICS | 0x00200000, None)
    try:
        acl = s.ACL()
        everyone = s.ConvertStringSidToSid("S-1-1-0")
        if mutation == "unsupported_ace":
            acl.AddAccessDeniedAce(s.ACL_REVISION, n.FILE_ADD_SUBDIRECTORY, everyone)
        flags = 0 if mutation == "changed_owner_only" else 3
        acl.AddAccessAllowedAceEx(s.ACL_REVISION, flags, n.FILE_ALL_ACCESS, w._current_user(api))
        mode = s.PROTECTED_DACL_SECURITY_INFORMATION
        if mutation == "writable_principal":
            acl.AddAccessAllowedAce(s.ACL_REVISION, n.FILE_ALL_ACCESS, everyone)
        elif mutation == "inheritance":
            mode = s.UNPROTECTED_DACL_SECURITY_INFORMATION
        s.SetSecurityInfo(handle, s.SE_FILE_OBJECT, s.DACL_SECURITY_INFORMATION | mode,
                          None, None, acl, None)
    finally:
        handle.Close()


def test_native_fully_protected_nested_path_is_read_only_and_pinned(native_nested_path):
    scope, api, intermediates, target, purpose = native_nested_path
    paths = (scope, *intermediates, target)
    before = native_descriptors(api, paths)
    contents = target.read_bytes() if purpose == "selected_project_json" else tuple(target.iterdir())
    with w.WindowsProtectedRootCharacterization.capture_for_characterization(
            str(scope), str(target), purpose, characterization=True, disposable_opt_in=True) as root:
        view = root.readiness()
        assert view["acl_verified"] and view["native_observation"] == "owner_only_acl_observed"
        assert_no_authority(view)
        assert str(scope) not in json.dumps(view)
        for intermediate in intermediates:
            with pytest.raises(OSError):
                intermediate.rename(intermediate.with_name(intermediate.name + "-replacement"))
        assert root.readiness()["acl_verified"]
    assert native_descriptors(api, paths) == before
    assert (target.read_bytes() if purpose == "selected_project_json" else tuple(target.iterdir())) == contents
    assert list(scope.iterdir()) == [intermediates[0]]
    assert list(intermediates[0].iterdir()) == [intermediates[1]]
    assert list(intermediates[1].iterdir()) == [target]


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("mutation", ["writable_principal", "inheritance", "unsupported_ace"])
def test_native_unsafe_intermediate_refused_without_acl_repair(native_nested_path, index, mutation):
    scope, api, intermediates, target, purpose = native_nested_path
    mutate_disposable_acl(intermediates[index], api, mutation)
    paths = (scope, *intermediates, target)
    before = native_descriptors(api, paths)
    with pytest.raises(ValueError, match="unsafe_acl|unsupported_acl"):
        w.WindowsProtectedRootCharacterization.capture_for_characterization(
            str(scope), str(target), purpose, characterization=True, disposable_opt_in=True)
    assert native_descriptors(api, paths) == before
    # The endpoint and scope remain protected; the intermediate alone rejects capture.
    for path in (scope, target):
        handle = w._open(path, path != target or purpose != "selected_project_json", api)
        try:
            assert w._acl(handle, api, w._current_user(api))
        finally:
            handle.Close()


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("mutation", ["writable_principal", "inheritance", "unsupported_ace", "changed_owner_only"])
def test_native_intermediate_acl_changes_invalidate_readiness(native_nested_path, index, mutation):
    scope, api, intermediates, target, purpose = native_nested_path
    with w.WindowsProtectedRootCharacterization.capture_for_characterization(
            str(scope), str(target), purpose, characterization=True, disposable_opt_in=True) as root:
        assert root.readiness()["acl_verified"]
        mutate_disposable_acl(intermediates[index], api, mutation)
        view = root.readiness()
        assert not view["acl_verified"] and view["native_observation"] == "unsafe_or_unavailable"
        assert_no_authority(view)


def test_native_intermediate_change_during_capture_refused(native_nested_path):
    scope, api, intermediates, target, purpose = native_nested_path
    original = w._open
    def change_after_open(path, directory, native_api):
        handle = original(path, directory, native_api)
        if path == target:
            mutate_disposable_acl(intermediates[0], api, "changed_owner_only")
        return handle
    with patch.object(w, "_open", change_after_open):
        with pytest.raises(ValueError, match="native_observation_changed"):
            w.WindowsProtectedRootCharacterization.capture_for_characterization(
                str(scope), str(target), purpose, characterization=True, disposable_opt_in=True)


def test_native_protected_dacl_created_and_verified_on_same_handle(native_root):
    scope, api, root = native_root
    view = root.readiness()
    assert view["acl_verified"] and view["native_observation"] == "owner_only_acl_observed"
    assert view["filesystem"] == "local_ntfs_observed" and view["identity"] == "handle_observed"
    assert_no_authority(view)
    assert w._identity(root._handle) == w._ordinary(root._path, directory=True)
    snapshot = w._acl(root._handle, api, w._current_user(api))
    assert len(snapshot) == 1 and snapshot[0][1] == 3  # explicit inheritable, not inherited
    assert str(scope) not in json.dumps(view) and snapshot[0][3] not in json.dumps(view)
    assert root._path.parent == scope
    assert list(scope.iterdir()) == [root._path] and not list(root._path.iterdir())


def test_existing_root_native_inspection_is_read_only(native_root):
    scope, _, first = native_root
    before = list(scope.iterdir()), first._identity
    with w.WindowsProtectedRootCharacterization.capture_for_characterization(
            str(scope), str(first._path), "private_journal", characterization=True,
            disposable_opt_in=True) as reopened:
        assert reopened.readiness()["acl_verified"]
        assert_no_authority(reopened.readiness())
    assert before == (list(scope.iterdir()), first._identity)


def test_native_live_handles_refuse_root_and_scope_substitution(native_root):
    scope, _, root = native_root
    for target in (root._path, scope):
        with pytest.raises(OSError):
            target.rename(target.with_name(target.name + "-replacement"))
    assert root.readiness()["acl_verified"]
    root.close()
    assert root.readiness()["native_observation"] == "closed"
    assert_no_authority(root.readiness())


@pytest.mark.parametrize("mutation", ["other_principal", "inheritance", "changed_owner_only"])
@pytest.mark.parametrize("target", ["root", "scope"])
def test_native_unsafe_acl_changes_invalidate_observation(native_root, mutation, target):
    scope, api, root = native_root
    _, c, f, s, n, _ = api
    handle = f.CreateFile(str(root._path if target == "root" else scope), c.READ_CONTROL | c.WRITE_DAC,
        c.FILE_SHARE_READ | c.FILE_SHARE_WRITE, None, c.OPEN_EXISTING,
        c.FILE_FLAG_BACKUP_SEMANTICS | 0x00200000, None)
    try:
        acl = s.ACL()
        flags = 0 if mutation == "changed_owner_only" else 3
        acl.AddAccessAllowedAceEx(s.ACL_REVISION, flags, n.FILE_ALL_ACCESS, w._current_user(api))
        mode = s.PROTECTED_DACL_SECURITY_INFORMATION
        if mutation == "other_principal":
            acl.AddAccessAllowedAce(s.ACL_REVISION, n.FILE_GENERIC_READ, s.ConvertStringSidToSid("S-1-1-0"))
        elif mutation == "inheritance":
            mode = s.UNPROTECTED_DACL_SECURITY_INFORMATION
        s.SetSecurityInfo(handle, s.SE_FILE_OBJECT, s.DACL_SECURITY_INFORMATION | mode,
                          None, None, acl, None)
    finally:
        handle.Close()
    view = root.readiness()
    assert not view["acl_verified"] and view["native_observation"] == "unsafe_or_unavailable"
    assert_no_authority(view)


def test_unsupported_native_filesystem_refused_before_creation(native_scope):
    scope, _ = native_scope
    with patch.object(w, "_filesystem", side_effect=ValueError("unsupported_filesystem")):
        with pytest.raises(ValueError, match="unsupported_filesystem"):
            w.WindowsProtectedRootCharacterization.provision_journal_for_characterization(
                str(scope), characterization=True, disposable_opt_in=True)
    assert not list(scope.iterdir())


def test_mapped_remote_drive_type_refused_before_creation(native_scope):
    scope, api = native_scope
    with patch.object(api[2], "GetDriveType", return_value=api[1].DRIVE_REMOTE):
        with pytest.raises(ValueError, match="unsupported_filesystem"):
            w.WindowsProtectedRootCharacterization.provision_journal_for_characterization(
                str(scope), characterization=True, disposable_opt_in=True)
    assert not list(scope.iterdir())


def test_failed_post_creation_observation_retains_only_new_journal_child(native_scope):
    scope, _ = native_scope
    original = w._open
    def fault(path, directory, api):
        if path.parent == scope:
            raise ValueError("interrupted_native_observation")
        return original(path, directory, api)
    with patch.object(w, "_open", fault):
        with pytest.raises(ValueError, match="interrupted_native_observation"):
            w.WindowsProtectedRootCharacterization.provision_journal_for_characterization(
                str(scope), characterization=True, disposable_opt_in=True)
    entries = list(scope.iterdir())
    assert len(entries) == 1 and entries[0].name.startswith("promptgraph-protected-journal-")
    assert not list(entries[0].iterdir())


def test_native_reparse_attribute_refused_on_open_handle(native_root):
    scope, api, root = native_root
    original = api[2].GetFileInformationByHandle
    def reparse(handle):
        info = original(handle)
        if w._identity(handle) == root._identity:
            return (info[0] | 0x400, *info[1:])
        return info
    with patch.object(api[2], "GetFileInformationByHandle", reparse):
        with pytest.raises(ValueError, match="reparse_or_link"):
            w.WindowsProtectedRootCharacterization.capture_for_characterization(str(scope),
                str(root._path), "private_journal", characterization=True, disposable_opt_in=True)


def test_native_unapproved_path_and_opt_in_refused_before_api(native_scope):
    scope, _ = native_scope
    with patch.object(w, "_api", side_effect=AssertionError("must not call API")):
        with pytest.raises(ValueError, match="unapproved_root"):
            w.WindowsProtectedRootCharacterization.capture_for_characterization(str(scope),
                str(scope.parent / "outside"), "promoted_assets", characterization=True, disposable_opt_in=True)
        with pytest.raises(ValueError, match="execution_unavailable"):
            w.WindowsProtectedRootCharacterization.provision_journal_for_characterization(str(scope))
    assert not list(scope.iterdir())


def test_native_missing_dependency_and_non_windows_are_closed():
    with patch.object(w.sys, "platform", "linux"):
        with pytest.raises(ValueError, match="unsupported_platform"):
            w._api()
    if sys.platform == "win32":
        with patch.dict("sys.modules", {"win32security": None}):
            with pytest.raises(ValueError, match="native_dependency_unavailable"):
                w._api()


def test_existing_inherited_scope_never_provisioned(tmp_path):
    if sys.platform != "win32":
        pytest.skip("Windows native characterization only")
    pytest.importorskip("win32security")
    before = list(tmp_path.iterdir())
    with pytest.raises(ValueError, match="unsafe_acl|unsupported_acl"):
        w.WindowsProtectedRootCharacterization.provision_journal_for_characterization(
            str(tmp_path), characterization=True, disposable_opt_in=True)
    assert before == list(tmp_path.iterdir())
