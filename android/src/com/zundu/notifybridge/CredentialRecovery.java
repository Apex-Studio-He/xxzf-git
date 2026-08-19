package com.zundu.notifybridge;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;

/** Explicit, user-approved recovery for credentials the server has rejected. */
final class CredentialRecovery {
    private CredentialRecovery() {}

    static void confirmAndClear(final Activity activity, final Runnable afterClear) {
        new AlertDialog.Builder(activity)
                .setTitle("清除失效凭据并重新配对？")
                .setMessage("仅当服务器已拒绝这台手机的设备凭据时使用。"
                        + "确认后只会清除本机失效凭据，然后由你重新配对；"
                        + "应用不会在未经确认时切换为匿名连接。")
                .setNegativeButton("取消", null)
                .setPositiveButton("清除并重新配对", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        Prefs.clearPairing(activity);
                        DiagnosticLog.add(activity, "warning", "CREDENTIAL_RESET_CONFIRMED");
                        if (afterClear != null) afterClear.run();
                    }
                })
                .show();
    }
}
