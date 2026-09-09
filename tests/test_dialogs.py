import os

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Native Windows COM dialog")
@pytest.mark.parametrize("folder,multiple", [(True, False), (False, True), (False, False)])
def test_native_dialog_configuration_and_release(tmp_path, folder, multiple):
    from simplemedia.dialogs import WindowsDialog

    with WindowsDialog(
        "Media picker test", folder, multiple, str(tmp_path), [("Media", "*.png;*.mp4")]
    ) as dialog:
        assert dialog.dialog
        assert dialog.initialized
    assert not dialog.dialog
    assert not dialog.initialized
