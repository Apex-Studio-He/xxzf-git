package com.zundu.notifybridge;

import android.Manifest;
import android.app.Activity;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.ClipData;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

import javax.net.ssl.HttpsURLConnection;

final class UpdateManager {
    static final String EXTRA_SHOW_UPDATE = "com.zundu.notifybridge.SHOW_UPDATE";
    static final long CHECK_INTERVAL_MS = 6L * 60L * 60L * 1000L;

    static final int AVAILABLE = 1;
    static final int NO_UPDATE = 2;
    static final int ERROR = 3;
    static final int READY = 4;
    static final int INSTALLER_OPENED = 5;
    static final int PERMISSION_REQUIRED = 6;

    interface Callback {
        void done(Result result);
    }

    static final class Result {
        final int status;
        final String message;
        final UpdateSecurity.ManifestData update;

        Result(int status, String message, UpdateSecurity.ManifestData update) {
            this.status = status;
            this.message = message;
            this.update = update;
        }
    }

    private static final ExecutorService EXECUTOR = Executors.newSingleThreadExecutor();
    private static final AtomicBoolean CHECKING = new AtomicBoolean(false);
    private static final int UPDATE_NOTIFICATION_ID = 9403;
    private static final String UPDATE_CHANNEL = "secure_updates";

    private UpdateManager() {}

    static void check(final Context context, final boolean manual, final Callback callback) {
        final Context application = context.getApplicationContext();
        if (!CHECKING.compareAndSet(false, true)) {
            if (callback != null) callback.done(new Result(ERROR, "正在检查更新", null));
            return;
        }
        EXECUTOR.execute(new Runnable() {
            @Override public void run() {
                Result result;
                Prefs.markUpdateCheck(application, System.currentTimeMillis());
                try {
                    UpdateSecurity.ManifestData data = fetchManifest(application);
                    if (!manual && Prefs.skippedUpdateVersion(application) == data.versionCode) {
                        result = new Result(NO_UPDATE, "已跳过版本 " + data.version, data);
                    } else {
                        result = new Result(AVAILABLE, "发现新版本 " + data.version, data);
                    }
                } catch (SecurityException noUpdate) {
                    if ("没有更高版本".equals(noUpdate.getMessage())) {
                        result = new Result(NO_UPDATE, "当前已是最新版本", null);
                    } else {
                        DiagnosticLog.add(application, "error", "UPDATE_SECURITY_REJECTED");
                        result = new Result(ERROR, "更新安全校验未通过", null);
                    }
                } catch (Exception error) {
                    DiagnosticLog.add(application, "warning", "UPDATE_CHECK_FAILED");
                    result = new Result(ERROR, "暂时无法检查更新", null);
                } finally {
                    CHECKING.set(false);
                }
                if (callback != null) callback.done(result);
            }
        });
    }

    static void checkInBackground(Context context) {
        if (!isCheckDue(context)) return;
        check(context, false, new Callback() {
            @Override public void done(Result result) {
                if (result.status == AVAILABLE && result.update != null) {
                    showAvailableNotification(context.getApplicationContext(), result.update);
                }
            }
        });
    }

    static boolean isCheckDue(Context context) {
        long last = Prefs.lastUpdateCheck(context);
        return last <= 0 || System.currentTimeMillis() - last >= CHECK_INTERVAL_MS;
    }

    static void skip(Context context, UpdateSecurity.ManifestData data) {
        Prefs.skipUpdateVersion(context, data.versionCode);
    }

    static void download(final Context context, final UpdateSecurity.ManifestData data,
                         final Callback callback) {
        final Context application = context.getApplicationContext();
        EXECUTOR.execute(new Runnable() {
            @Override public void run() {
                try {
                    File apk = downloadVerified(application, data);
                    validateApk(application, apk, data);
                    if (!Prefs.savePendingUpdate(application, toJson(data).toString())) {
                        throw new IllegalStateException("cannot persist verified update");
                    }
                    callback.done(new Result(READY, "更新包已安全下载", data));
                } catch (Exception error) {
                    clearPendingUpdate(application);
                    DiagnosticLog.add(application, "error", "UPDATE_DOWNLOAD_REJECTED");
                    callback.done(new Result(ERROR, "更新包下载或校验失败", null));
                }
            }
        });
    }

    static boolean hasPendingUpdate(Context context) {
        return !Prefs.get(context).getString(Prefs.KEY_PENDING_UPDATE_MANIFEST, "").isEmpty()
                && updateFile(context).isFile();
    }

    static String pendingVersion(Context context) {
        try {
            return new JSONObject(Prefs.get(context).getString(
                    Prefs.KEY_PENDING_UPDATE_MANIFEST, "")).getString("version");
        } catch (Exception ignored) {
            return "";
        }
    }

    static void continueInstallation(final Activity activity, final Callback callback) {
        EXECUTOR.execute(new Runnable() {
            @Override public void run() {
                try {
                    String raw = Prefs.get(activity).getString(
                            Prefs.KEY_PENDING_UPDATE_MANIFEST, "");
                    if (raw.isEmpty()) throw new SecurityException("no pending update");
                    UpdateSecurity.ManifestData data = parseAndVerify(
                            new JSONObject(raw), currentVersionCode(activity));
                    validateApk(activity, updateFile(activity), data);
                    activity.runOnUiThread(new Runnable() {
                        @Override public void run() {
                            openInstaller(activity, data, callback);
                        }
                    });
                } catch (Exception error) {
                    clearPendingUpdate(activity);
                    callback.done(new Result(ERROR, "已下载更新包校验失败", null));
                }
            }
        });
    }

    static void clearPendingUpdate(Context context) {
        Prefs.clearPendingUpdate(context);
        File file = updateFile(context);
        if (file.exists()) file.delete();
        File partial = new File(file.getParentFile(), file.getName() + ".part");
        if (partial.exists()) partial.delete();
        NotificationManager manager = (NotificationManager)
                context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) manager.cancel(UPDATE_NOTIFICATION_ID);
    }

    static long currentVersionCode(Context context) {
        try {
            PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
            return Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode;
        } catch (Exception ignored) {
            return 0;
        }
    }

    static String currentVersionName(Context context) {
        try {
            String value = context.getPackageManager()
                    .getPackageInfo(context.getPackageName(), 0).versionName;
            return value == null ? "" : value;
        } catch (Exception ignored) {
            return "";
        }
    }

    private static UpdateSecurity.ManifestData fetchManifest(Context context) throws Exception {
        URL url = new URL(UpdateSecurity.MANIFEST_URL);
        HttpsURLConnection connection = (HttpsURLConnection) url.openConnection();
        try {
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(5000);
            connection.setReadTimeout(8000);
            connection.setRequestMethod("GET");
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Accept-Encoding", "identity");
            connection.setRequestProperty("Connection", "close");
            int status = connection.getResponseCode();
            if (status >= 300 && status < 400) throw new SecurityException("redirect rejected");
            if (status != HttpURLConnection.HTTP_OK
                    || !UpdateSecurity.MANIFEST_URL.equals(connection.getURL().toExternalForm())) {
                throw new IllegalStateException("manifest unavailable");
            }
            byte[] body = readBounded(connection.getInputStream(), UpdateSecurity.MAX_MANIFEST_BYTES);
            return parseAndVerify(
                    new JSONObject(new String(body, StandardCharsets.UTF_8)),
                    currentVersionCode(context));
        } finally {
            connection.disconnect();
        }
    }

    private static UpdateSecurity.ManifestData parseAndVerify(JSONObject object, long currentCode)
            throws Exception {
        Map<String, Object> values = new HashMap<>();
        Iterator<String> keys = object.keys();
        while (keys.hasNext()) {
            String key = keys.next();
            values.put(key, object.get(key));
        }
        return UpdateSecurity.validateAndVerify(values, currentCode);
    }

    private static File downloadVerified(Context context, UpdateSecurity.ManifestData data)
            throws Exception {
        UpdateSecurity.validateDownloadUrl(data.url, data.version);
        File target = updateFile(context);
        File directory = target.getParentFile();
        if (!directory.isDirectory() && !directory.mkdirs()) {
            throw new IllegalStateException("cannot create update directory");
        }
        String trustedRoot = new File(context.getFilesDir(), "updates").getCanonicalPath();
        if (!target.getCanonicalPath().startsWith(trustedRoot + File.separator)) {
            throw new SecurityException("invalid update directory");
        }
        File partial = new File(directory, target.getName() + ".part");
        if (partial.exists() && !partial.delete()) throw new IllegalStateException("stale update");

        HttpsURLConnection connection = (HttpsURLConnection) new URL(data.url).openConnection();
        try {
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(7000);
            connection.setReadTimeout(30000);
            connection.setRequestMethod("GET");
            connection.setRequestProperty("Accept-Encoding", "identity");
            connection.setRequestProperty("Connection", "close");
            int status = connection.getResponseCode();
            if (status >= 300 && status < 400) throw new SecurityException("redirect rejected");
            if (status != HttpURLConnection.HTTP_OK
                    || !data.url.equals(connection.getURL().toExternalForm())) {
                throw new IllegalStateException("update unavailable");
            }
            long declared = connection.getContentLengthLong();
            if (declared >= 0 && declared != data.size) {
                throw new SecurityException("unexpected content length");
            }
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            long total = 0;
            try (InputStream input = connection.getInputStream();
                 FileOutputStream output = new FileOutputStream(partial, false)) {
                byte[] buffer = new byte[32 * 1024];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    total += count;
                    if (total > data.size || total > UpdateSecurity.MAX_PACKAGE_BYTES) {
                        throw new SecurityException("update exceeds declared size");
                    }
                    output.write(buffer, 0, count);
                    digest.update(buffer, 0, count);
                }
                output.flush();
                output.getFD().sync();
            }
            if (total != data.size || !data.sha256.equals(hex(digest.digest()))) {
                throw new SecurityException("update digest mismatch");
            }
        } catch (Exception error) {
            partial.delete();
            throw error;
        } finally {
            connection.disconnect();
        }
        if (target.exists() && !target.delete()) {
            partial.delete();
            throw new IllegalStateException("cannot replace old update");
        }
        if (!partial.renameTo(target)) {
            partial.delete();
            throw new IllegalStateException("cannot finalize update");
        }
        return target;
    }

    private static void validateApk(
            Context context, File apk, UpdateSecurity.ManifestData data) throws Exception {
        if (!apk.isFile() || apk.length() != data.size
                || !data.sha256.equals(fileSha256(apk))) {
            throw new SecurityException("APK digest mismatch");
        }
        PackageManager manager = context.getPackageManager();
        int flags = Build.VERSION.SDK_INT >= 28
                ? PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES;
        PackageInfo archive = manager.getPackageArchiveInfo(apk.getAbsolutePath(), flags);
        PackageInfo installed = manager.getPackageInfo(context.getPackageName(), flags);
        if (archive == null || !context.getPackageName().equals(archive.packageName)) {
            throw new SecurityException("APK package mismatch");
        }
        long archiveCode = Build.VERSION.SDK_INT >= 28
                ? archive.getLongVersionCode() : archive.versionCode;
        if (archiveCode != data.versionCode || archive.versionName == null
                || !data.version.equals(archive.versionName)) {
            throw new SecurityException("APK version mismatch");
        }
        if (!certificateDigests(archive).equals(certificateDigests(installed))) {
            throw new SecurityException("APK signer mismatch");
        }
    }

    private static Set<String> certificateDigests(PackageInfo info) throws Exception {
        Signature[] signatures;
        if (Build.VERSION.SDK_INT >= 28) {
            if (info.signingInfo == null) throw new SecurityException("missing APK signer");
            signatures = info.signingInfo.getApkContentsSigners();
        } else {
            signatures = info.signatures;
        }
        if (signatures == null || signatures.length == 0) {
            throw new SecurityException("missing APK signer");
        }
        Set<String> digests = new HashSet<>();
        for (Signature signature : signatures) {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digests.add(hex(digest.digest(signature.toByteArray())));
        }
        return digests;
    }

    private static void openInstaller(
            Activity activity, UpdateSecurity.ManifestData data, Callback callback) {
        if (Build.VERSION.SDK_INT >= 26
                && !activity.getPackageManager().canRequestPackageInstalls()) {
            Intent settings = new Intent(
                    Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:" + activity.getPackageName()));
            activity.startActivity(settings);
            callback.done(new Result(
                    PERMISSION_REQUIRED, "请允许本应用安装更新，然后返回继续", data));
            return;
        }
        Uri uri = UpdateFileProvider.contentUri();
        Intent installer = new Intent(Intent.ACTION_VIEW);
        installer.setDataAndType(uri, "application/vnd.android.package-archive");
        installer.setClipData(ClipData.newRawUri("verified-update", uri));
        installer.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        if (installer.resolveActivity(activity.getPackageManager()) == null) {
            callback.done(new Result(ERROR, "系统安装器不可用", data));
            return;
        }
        UpdateRecovery.schedule(activity, data.versionCode);
        activity.startActivity(installer);
        callback.done(new Result(INSTALLER_OPENED, "已交给系统安装器确认", data));
    }

    private static void showAvailableNotification(
            Context context, UpdateSecurity.ManifestData data) {
        if (Build.VERSION.SDK_INT >= 33
                && context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) return;
        NotificationManager manager = (NotificationManager)
                context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) return;
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(
                    UPDATE_CHANNEL, "软件更新", NotificationManager.IMPORTANCE_DEFAULT);
            channel.setDescription("转发安全更新提醒");
            manager.createNotificationChannel(channel);
        }
        Intent intent = new Intent(context, MainActivity.class)
                .putExtra(EXTRA_SHOW_UPDATE, true)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pending = PendingIntent.getActivity(
                context,
                91,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        android.app.Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                ? new android.app.Notification.Builder(context, UPDATE_CHANNEL)
                : new android.app.Notification.Builder(context);
        builder.setSmallIcon(com.zundu.notifybridge.R.drawable.ic_launcher)
                .setContentTitle("转发有新版本")
                .setContentText("Android " + data.version + " 可更新")
                .setContentIntent(pending)
                .setAutoCancel(true)
                .setOnlyAlertOnce(true);
        manager.notify(UPDATE_NOTIFICATION_ID, builder.build());
    }

    private static JSONObject toJson(UpdateSecurity.ManifestData data) throws Exception {
        return new JSONObject()
                .put("schema", data.schema)
                .put("channel", data.channel)
                .put("platform", data.platform)
                .put("versionCode", data.versionCode)
                .put("version", data.version)
                .put("url", data.url)
                .put("sha256", data.sha256)
                .put("size", data.size)
                .put("publishedAt", data.publishedAt)
                .put("notes", data.notes)
                .put("keyId", data.keyId)
                .put("signature", data.signature);
    }

    private static byte[] readBounded(InputStream input, int limit) throws Exception {
        try (InputStream stream = input; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[4096];
            int total = 0;
            int count;
            while ((count = stream.read(buffer)) != -1) {
                total += count;
                if (total > limit) throw new SecurityException("manifest too large");
                output.write(buffer, 0, count);
            }
            return output.toByteArray();
        }
    }

    private static String fileSha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (FileInputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[32 * 1024];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        return hex(digest.digest());
    }

    private static String hex(byte[] value) {
        StringBuilder result = new StringBuilder(value.length * 2);
        for (byte item : value) result.append(String.format(java.util.Locale.ROOT, "%02x", item));
        return result.toString();
    }

    private static File updateFile(Context context) {
        return new File(new File(context.getFilesDir(), "updates"), UpdateFileProvider.FILE_NAME);
    }
}
