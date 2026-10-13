"""Real disposable Windows ACL/file observations; injected faults labeled."""
import io
import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import pytest

from core import generation_windows_protected_assets as a
from core import generation_windows_protected_storage as w
from core.comfy_output_containment import ContainmentLimits
from test_generation_windows_protected_storage import (
    native_scope, mutate_disposable_acl, native_descriptors,
)


def png():
    output = io.BytesIO()
    Image.new("RGB", (2, 3), "white").save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def owner(native_scope):
    scope, api = native_scope
    with a.WindowsProtectedAssetsCharacterization.provision_for_characterization(
            str(scope), characterization=True, disposable_opt_in=True) as owner:
        yield owner, scope, api


def assert_closed_gates(view):
    for key in ("execution_available", "protected_storage_available", "recovery_execution_allowed",
                "attachment_allowed", "publication_allowed", "project_save_allowed", "cleanup_allowed",
                "retry_allowed", "power_loss_guarantee", "same_user_process_authentication", "cross_file_transaction"):
        assert view[key] is False
    assert view["authorship"] == "unverified"
    assert view["directory_durability"] == "unsupported"


@pytest.mark.parametrize("purpose", a._PURPOSES)
def test_real_native_creation_pins_initial_file_and_checks_bytes(owner, purpose):
    store, scope, api = owner
    image = store.create_image_for_characterization(purpose, png())
    path, handle, identity, acl = store._files[(image.purpose, image.storage_identity)]
    assert w._identity(handle) == identity == w._ordinary(path, directory=False)
    assert w._acl(handle, api, w._current_user(api)) == acl[0]
    assert len(acl[0]) == 1 and acl[0][0][1] == 3
    assert path.read_bytes() == png()
    assert store.inspect_image_for_characterization(image) is image
    assert (image.width, image.height, image.image_format) == (2, 3, "PNG")
    for target in (path, path.parent, scope):
        with pytest.raises(OSError):
            target.rename(target.with_name(target.name + "-replaced"))
    view = store.readiness()
    assert view["asset_observation"] == "observed" and view["integrity"] == "verified_bytes"
    assert str(scope) not in json.dumps(view) and image.content_sha256 not in json.dumps(view)
    assert_closed_gates(view)
    store.close()
    assert path.exists() and store.readiness()["asset_observation"] == "closed"
    with pytest.raises(ValueError, match="closed_observation"):
        store.inspect_image_for_characterization(image)


@pytest.mark.parametrize("purpose", a._PURPOSES)
@pytest.mark.parametrize("target", ["root", "file"])
@pytest.mark.parametrize("mutation", ["changed_owner_only", "inheritance", "writable_principal"])
def test_real_native_acl_drift_invalidates_original_snapshot(owner, purpose, target, mutation):
    store, _, api = owner
    image = store.create_image_for_characterization(purpose, png())
    path = store._files[(image.purpose, image.storage_identity)][0]
    mutate_disposable_acl(path if target == "file" else path.parent, api, mutation)
    with pytest.raises(ValueError, match="native_observation_changed|unsafe_acl|unsupported_acl|protected_root_unavailable"):
        store.inspect_image_for_characterization(image)
    assert path.exists()
    assert store.readiness()["asset_observation"] == "unsafe_or_unavailable"
    assert_closed_gates(store.readiness())


@pytest.mark.parametrize("purpose", a._PURPOSES)
@pytest.mark.parametrize("boundary", ["after_file_create", "after_file_write", "after_file_sync"])
def test_injected_interruption_retains_real_native_evidence_no_retry(owner, purpose, boundary):
    store, _, api = owner
    def fault(point):
        if point == boundary:
            raise RuntimeError("injected interruption")
    store._fault = fault
    with pytest.raises(RuntimeError, match="injected interruption"):
        store.create_image_for_characterization(purpose, png())
    assert len(store._files) == 1 and not store._images
    path, handle, _, acl = next(iter(store._files.values()))
    assert path.exists() and w._acl(handle, api, w._current_user(api)) == acl[0]
    assert path.read_bytes() == (b"" if boundary == "after_file_create" else png())
    assert store.readiness()["asset_observation"] == "retained_uncertain"
    with pytest.raises(ValueError, match="inspect_only_or_uncertain"):
        store.create_image_for_characterization(purpose, png())
    assert len(list(path.parent.iterdir())) == 1
    store.close()
    assert path.exists()


@pytest.mark.parametrize("purpose", a._PURPOSES)
def test_real_native_content_change_is_retained_and_never_verified(owner, purpose):
    store, _, _ = owner
    image = store.create_image_for_characterization(purpose, png())
    path = store._files[(image.purpose, image.storage_identity)][0]
    changed = io.BytesIO()
    Image.new("RGB", (2, 3), "black").save(changed, format="PNG")
    path.write_bytes(changed.getvalue())
    with pytest.raises(ValueError, match="content_changed"):
        store.inspect_image_for_characterization(image)
    assert path.read_bytes() == changed.getvalue()
    assert store.readiness()["integrity"] != "verified_bytes"


def test_unexpected_existing_file_exclusive_collision_never_overwritten(owner):
    store, _, _ = owner
    root = store._roots["temporary_containment"]
    unexpected = root._path / "keep.png"
    unexpected.write_bytes(b"retain")
    with pytest.raises(ValueError, match="unexpected_existing_file"):
        store.create_image_for_characterization("temporary_containment", png())
    assert unexpected.read_bytes() == b"retain" and not store._files


def test_same_filename_in_other_purpose_is_unmanaged_and_blocks_creation(owner):
    store, _, _ = owner
    managed = store.create_image_for_characterization("temporary_containment", png())
    managed_path = store._files[(managed.purpose, managed.storage_identity)][0]
    promoted_root = store._roots["promoted_assets"]
    unmanaged_path = promoted_root._path / managed_path.name
    _, c, f, _, _, _ = promoted_root._api
    handle = f.CreateFile(str(unmanaged_path), c.GENERIC_READ | c.GENERIC_WRITE | c.READ_CONTROL,
        c.FILE_SHARE_READ | c.FILE_SHARE_WRITE, w._security_attributes(promoted_root._api, promoted_root._user),
        c.CREATE_NEW, c.FILE_ATTRIBUTE_NORMAL, None)
    try:
        _, written = f.WriteFile(handle, b"unmanaged retained evidence")
        assert written == len(b"unmanaged retained evidence")
        f.FlushFileBuffers(handle)
    finally:
        handle.Close()
    managed_before = managed_path.read_bytes()
    unmanaged_before = unmanaged_path.read_bytes()

    with pytest.raises(ValueError, match="unexpected_existing_file"):
        store.create_image_for_characterization("promoted_assets", png())

    assert managed_path.exists() and unmanaged_path.exists()
    assert managed_path.read_bytes() == managed_before
    assert unmanaged_path.read_bytes() == unmanaged_before
    assert {path.name for path in store._roots["temporary_containment"]._path.iterdir()} == {managed_path.name}
    assert {path.name for path in promoted_root._path.iterdir()} == {unmanaged_path.name}
    assert set(store._files) == {("temporary_containment", managed_path.name)}
    assert store.readiness()["asset_observation"] == "retained_uncertain"


def test_normal_staging_and_promoted_creation_remain_available(owner):
    store, _, _ = owner
    staging = store.create_image_for_characterization("temporary_containment", png())
    promoted = store.create_image_for_characterization("promoted_assets", png())

    assert staging.purpose == "temporary_containment"
    assert promoted.purpose == "promoted_assets"
    assert (staging.purpose, staging.storage_identity) != (promoted.purpose, promoted.storage_identity)
    assert store.inspect_image_for_characterization(staging) is staging
    assert store.inspect_image_for_characterization(promoted) is promoted
    assert store.readiness()["image_count"] == 2


def test_injected_host_name_collision_retains_verified_original(owner):
    store, _, _ = owner
    class Name:
        hex = "a" * 32
    with patch.object(a.uuid, "uuid4", return_value=Name()):
        image = store.create_image_for_characterization("promoted_assets", png())
        path = store._files[(image.purpose, image.storage_identity)][0]
        with pytest.raises(Exception):
            store.create_image_for_characterization("promoted_assets", png())
        assert path.read_bytes() == png() and len(store._files) == 1
    assert store.readiness()["asset_observation"] == "retained_uncertain"


def test_real_native_fresh_reopen_only_observes_no_old_authority(owner):
    store, scope, _ = owner
    originals = [store.create_image_for_characterization(purpose, png()) for purpose in a._PURPOSES]
    paths = {p: str(r._path) for p, r in store._roots.items()}
    store.close()
    with a.WindowsProtectedAssetsCharacterization.reopen_for_characterization(
            str(scope), paths, characterization=True, disposable_opt_in=True) as reopened:
        images = reopened.inspect_existing_for_characterization()
        assert len(images) == 2
        assert {image.purpose for image in images} == set(a._PURPOSES)
        assert all(image.content_sha256 == originals[0].content_sha256 for image in images)
        for image in images:
            assert reopened.inspect_image_for_characterization(image) is image
        view = reopened.readiness()
        assert view["image_count"] == 2 and view["integrity"] == "verified_bytes"
        assert_closed_gates(view)
        for image in originals:
            with pytest.raises(ValueError, match="image_owner_mismatch"):
                reopened.inspect_image_for_characterization(image)
        with pytest.raises(ValueError, match="inspect_only_or_uncertain"):
            reopened.create_image_for_characterization("promoted_assets", png())


def test_real_native_incomplete_file_fresh_reopen_retains_evidence(owner):
    store, scope, _ = owner
    def fault(point):
        if point == "after_file_create":
            raise RuntimeError("injected")
    store._fault = fault
    with pytest.raises(RuntimeError):
        store.create_image_for_characterization("temporary_containment", png())
    path = next(iter(store._files.values()))[0]
    paths = {p: str(r._path) for p, r in store._roots.items()}
    store.close()
    with a.WindowsProtectedAssetsCharacterization.reopen_for_characterization(
            str(scope), paths, characterization=True, disposable_opt_in=True) as reopened:
        with pytest.raises(ValueError, match="image_byte_limit"):
            reopened.inspect_existing_for_characterization()
    assert path.exists() and path.read_bytes() == b""


def test_real_native_failed_inventory_cannot_retry_or_publish_partial_images(owner):
    store, scope, _ = owner
    originals = [store.create_image_for_characterization(purpose, png()) for purpose in a._PURPOSES]
    files = [store._files[(image.purpose, image.storage_identity)][0] for image in originals]
    paths = {p: str(r._path) for p, r in store._roots.items()}
    store.close()
    # The staging image decodes first; the promoted image makes the full inventory fail.
    files[1].write_bytes(b"invalid image")
    with a.WindowsProtectedAssetsCharacterization.reopen_for_characterization(
            str(scope), paths, characterization=True, disposable_opt_in=True) as reopened:
        with pytest.raises(Exception, match="invalid_image_content"):
            reopened.inspect_existing_for_characterization()
        assert not reopened._images
        assert reopened.readiness()["image_count"] == 0
        assert reopened.readiness()["integrity"] == "not_verified"
        assert files[0].read_bytes() == png() and files[1].read_bytes() == b"invalid image"
        # Repairing retained evidence does not permit a retry by its uncertain owner.
        files[1].write_bytes(png())
        with pytest.raises(ValueError, match="fresh_inspect_only_owner_required"):
            reopened.inspect_existing_for_characterization()
        assert not reopened._images
        assert_closed_gates(reopened.readiness())
    assert all(path.exists() and path.read_bytes() == png() for path in files)
    with a.WindowsProtectedAssetsCharacterization.reopen_for_characterization(
            str(scope), paths, characterization=True, disposable_opt_in=True) as fresh:
        images = fresh.inspect_existing_for_characterization()
        assert len(images) == 2
        assert all(fresh.inspect_image_for_characterization(image) is image for image in images)
        assert fresh.readiness()["image_count"] == 2
        assert fresh.readiness()["integrity"] == "verified_bytes"
        assert_closed_gates(fresh.readiness())


def test_native_hardlink_and_identity_substitution_refused_after_close(owner):
    store, scope, _ = owner
    image = store.create_image_for_characterization("promoted_assets", png())
    path = store._files[(image.purpose, image.storage_identity)][0]
    paths = {p: str(r._path) for p, r in store._roots.items()}
    store.close()
    replaced = path.with_name("b" * 32 + ".png")
    path.rename(replaced)
    path.write_bytes(png())
    with pytest.raises(ValueError, match="closed_observation"):
        store.inspect_image_for_characterization(image)
    alias = path.with_name("c" * 32 + ".png")
    alias.hardlink_to(path)
    with a.WindowsProtectedAssetsCharacterization.reopen_for_characterization(
            str(scope), paths, characterization=True, disposable_opt_in=True) as reopened:
        with pytest.raises(ValueError, match="multiple_file_links"):
            reopened.inspect_existing_for_characterization()
    assert path.exists() and alias.exists() and replaced.exists()


def test_capacity_and_format_bounds_before_write(owner):
    store, _, _ = owner
    store._limits = ContainmentLimits(image_bytes=1, request_bytes=1, aggregate_bytes=1, images=1)
    with pytest.raises(ValueError, match="storage_capacity"):
        store.create_image_for_characterization("temporary_containment", png())
    assert not store._files


def test_invalid_image_retained_without_decode_policy_relaxation(owner):
    store, _, _ = owner
    with pytest.raises(Exception, match="invalid_image_content"):
        store.create_image_for_characterization("temporary_containment", b"bad")
    assert next(iter(store._files.values()))[0].read_bytes() == b"bad"
    assert not store._images and store.readiness()["asset_observation"] == "retained_uncertain"


def test_unapproved_overlap_and_dependency_failures_before_creation(native_scope):
    scope, _ = native_scope
    with patch.object(w, "_api", side_effect=AssertionError("no native calls")):
        for paths, code in [({p: str(scope / "same") for p in a._PURPOSES}, "purpose_overlap"),
                            ({p: str(scope.parent / p) for p in a._PURPOSES}, "unapproved_root")]:
            with pytest.raises(ValueError, match=code):
                a.WindowsProtectedAssetsCharacterization.reopen_for_characterization(
                    str(scope), paths, characterization=True, disposable_opt_in=True)
    with patch.object(w, "_filesystem", side_effect=ValueError("unsupported_filesystem")):
        with pytest.raises(ValueError, match="unsupported_filesystem"):
            a.WindowsProtectedAssetsCharacterization.provision_for_characterization(
                str(scope), characterization=True, disposable_opt_in=True)
    assert not list(scope.iterdir())


def test_opt_in_and_unsupported_platform_are_closed(tmp_path):
    with pytest.raises(ValueError, match="execution_unavailable"):
        a.WindowsProtectedAssetsCharacterization.provision_for_characterization(str(tmp_path))
    with patch.object(w.sys, "platform", "linux"):
        with pytest.raises(ValueError, match="unsupported_platform"):
            a.WindowsProtectedAssetsCharacterization.provision_for_characterization(
                str(tmp_path), characterization=True, disposable_opt_in=True)


def test_injected_missing_native_dependency_refused_before_creation(native_scope):
    scope, _ = native_scope
    with patch.dict("sys.modules", {"win32security": None}):
        with pytest.raises(ValueError, match="native_dependency_unavailable"):
            a.WindowsProtectedAssetsCharacterization.provision_for_characterization(
                str(scope), characterization=True, disposable_opt_in=True)
    assert not list(scope.iterdir())


@pytest.mark.parametrize("mutation", ["inheritance", "writable_principal"])
def test_real_native_unsafe_scope_or_intermediate_never_repaired(native_scope, mutation):
    scope, api = native_scope
    user = w._current_user(api)
    intermediate = scope / "intermediate"
    api[2].CreateDirectory(str(intermediate), w._security_attributes(api, user))
    paths = {}
    for purpose in a._PURPOSES:
        path = intermediate / purpose
        api[2].CreateDirectory(str(path), w._security_attributes(api, user))
        paths[purpose] = str(path)
    mutate_disposable_acl(intermediate, api, mutation)
    with pytest.raises(ValueError, match="unsafe_acl|unsupported_acl"):
        a.WindowsProtectedAssetsCharacterization.reopen_for_characterization(
            str(scope), paths, characterization=True, disposable_opt_in=True)
    assert all(not list(Path(p).iterdir()) for p in paths.values())
    mutate_disposable_acl(scope, api, mutation)
    before = list(scope.iterdir())
    with pytest.raises(ValueError, match="unsafe_acl|unsupported_acl"):
        a.WindowsProtectedAssetsCharacterization.provision_for_characterization(
            str(scope), characterization=True, disposable_opt_in=True)
    assert list(scope.iterdir()) == before


def test_real_native_host_provisioned_nested_roots_reopen_read_only(native_scope):
    scope, api = native_scope
    _, c, f, _, _, _ = api
    user = w._current_user(api)
    first, second = scope / "first", scope / "first" / "second"
    paths = {p: str(second / p) for p in a._PURPOSES}
    directories = (scope, first, second, *(Path(p) for p in paths.values()))
    for directory in directories[1:]:
        f.CreateDirectory(str(directory), w._security_attributes(api, user))
    files = []
    for index, purpose in enumerate(a._PURPOSES):
        path = Path(paths[purpose]) / (str(index + 1) * 32 + ".png")
        handle = f.CreateFile(str(path), c.GENERIC_READ | c.GENERIC_WRITE,
            c.FILE_SHARE_READ | c.FILE_SHARE_WRITE, w._security_attributes(api, user),
            c.CREATE_NEW, c.FILE_ATTRIBUTE_NORMAL, None)
        try:
            f.WriteFile(handle, png())
            f.FlushFileBuffers(handle)
        finally:
            handle.Close()
        files.append(path)
    before = native_descriptors(api, (*directories, *files))
    with a.WindowsProtectedAssetsCharacterization.reopen_for_characterization(
            str(scope), paths, characterization=True, disposable_opt_in=True) as reopened:
        images = reopened.inspect_existing_for_characterization()
        assert {image.purpose for image in images} == set(a._PURPOSES)
        assert all(image.content_sha256 == hashlib.sha256(png()).hexdigest() for image in images)
        assert_closed_gates(reopened.readiness())
        for root in reopened._roots.values():
            assert {row[0] for row in root._observations} == {scope, first, second, root._path}
        for intermediate in (first, second):
            with pytest.raises(OSError):
                intermediate.rename(intermediate.with_name(intermediate.name + "-replaced"))
        with pytest.raises(ValueError, match="inspect_only_or_uncertain"):
            reopened.create_image_for_characterization("temporary_containment", png())
    assert native_descriptors(api, (*directories, *files)) == before
    assert all(path.read_bytes() == png() for path in files)


def test_real_native_junction_refused_without_following_or_cleanup(native_scope):
    scope, api = native_scope
    target = scope / "target"
    api[2].CreateDirectory(str(target), w._security_attributes(api, w._current_user(api)))
    junction = scope / "junction"
    created = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)],
                             capture_output=True, check=False)
    assert created.returncode == 0, created.stderr.decode(errors="replace")
    assert junction.lstat().st_file_attributes & 0x400
    paths = {"temporary_containment": str(junction), "promoted_assets": str(scope / "unused")}
    with pytest.raises(ValueError, match="reparse_or_link"):
        a.WindowsProtectedAssetsCharacterization.reopen_for_characterization(
            str(scope), paths, characterization=True, disposable_opt_in=True)
    assert junction.lstat().st_file_attributes & 0x400 and not list(target.iterdir())


def test_observed_acl_change_cannot_restore_old_file_observation(owner):
    store, _, api = owner
    image = store.create_image_for_characterization("temporary_containment", png())
    path = store._files[(image.purpose, image.storage_identity)][0]
    mutate_disposable_acl(path, api, "changed_owner_only")
    assert store.readiness()["asset_observation"] == "unsafe_or_unavailable"
    # Restore the initial descriptor in a disposable fixture only.
    mutate_disposable_acl(path, api, "original")
    with pytest.raises(ValueError, match="invalidated_observation"):
        store.inspect_image_for_characterization(image)
    assert store.readiness()["integrity"] != "verified_bytes" and path.exists()


def test_real_native_owner_only_acl_revision_change_invalidates_file(owner):
    store, scope, api = owner
    image = store.create_image_for_characterization("promoted_assets", png())
    path = store._files[(image.purpose, image.storage_identity)][0]
    paths = {p: str(r._path) for p, r in store._roots.items()}
    store.close()
    # SetSecurityInfo normalizes file inheritance flags to zero on this host.
    mutate_disposable_acl(path, api, "changed_owner_only")
    _, c, f, s, n, _ = api
    with a.WindowsProtectedAssetsCharacterization.reopen_for_characterization(
            str(scope), paths, characterization=True, disposable_opt_in=True) as reopened:
        reopened.inspect_existing_for_characterization()
        _, original, _, snapshot = next(iter(reopened._files.values()))
        handle = f.CreateFile(str(path), c.READ_CONTROL | c.WRITE_DAC,
            c.FILE_SHARE_READ | c.FILE_SHARE_WRITE, None, c.OPEN_EXISTING, c.FILE_ATTRIBUTE_NORMAL, None)
        try:
            acl = s.ACL()
            acl.AddAccessAllowedAceEx(s.ACL_REVISION_DS, 0, n.FILE_ALL_ACCESS, w._current_user(api))
            assert acl.GetAclRevision() == s.ACL_REVISION_DS
            s.SetSecurityInfo(handle, s.SE_FILE_OBJECT,
                s.DACL_SECURITY_INFORMATION | s.PROTECTED_DACL_SECURITY_INFORMATION,
                None, None, acl, None)
        finally:
            handle.Close()
        # Equal owner-only ACEs still leave a different native DACL snapshot.
        assert w._acl(original, api, w._current_user(api)) == snapshot[0]
        with pytest.raises(ValueError, match="native_observation_changed"):
            reopened._check()
    assert path.exists()


def test_modules_imported_from_isolated_worktree():
    root = Path(__file__).resolve().parents[1]
    assert Path(a.__file__).resolve().is_relative_to(root)
    assert Path(w.__file__).resolve().is_relative_to(root)
