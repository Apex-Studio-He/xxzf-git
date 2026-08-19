package com.zundu.notifybridge;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import com.google.zxing.BarcodeFormat;
import com.google.zxing.MultiFormatWriter;
import com.google.zxing.common.BitMatrix;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

public class ReceiverPairActivity extends Activity {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private TextView connectionStatus;
    private TextView code;
    private TextView expiry;
    private ImageView qr;
    private Button generate;
    private Switch enabled;
    private RadioGroup privacy;
    private LinearLayout sendersList;
    private TextView sendersSummary;
    private List<SenderDevice> senders = new ArrayList<>();
    private String pairingId = "";
    private long expiresAt;
    private boolean changing;
    private boolean sendersLoading;
    private final Runnable poll = new Runnable() {
        @Override public void run() {
            if (pairingId.isEmpty() || System.currentTimeMillis() >= expiresAt) {
                if (expiresAt > 0 && System.currentTimeMillis() >= expiresAt) {
                    expiry.setText("配对码已失效");
                    expiry.setTextColor(Ui.RED);
                }
                return;
            }
            refreshExpiry();
            ReceiverClient.pairingStatus(ReceiverPairActivity.this, pairingId,
                    new ReceiverClient.StatusCallback() {
                @Override public void done(final boolean ok, final String message, final boolean paired) {
                    runOnUiThread(new Runnable() {
                        @Override public void run() {
                            if (isFinishing()) return;
                            if (paired) {
                                pairingId = "";
                                connectionStatus.setText("已连接，可以接收通知");
                                connectionStatus.setTextColor(Ui.GREEN);
                                code.setText("已配对");
                                expiry.setText("设备编号 " + Prefs.localReceiverFingerprint(
                                        ReceiverPairActivity.this));
                                qr.setImageResource(com.zundu.notifybridge.R.drawable.ic_launcher);
                                Prefs.setReceiveEnabled(ReceiverPairActivity.this, true);
                                ReceiverBridgeService.start(ReceiverPairActivity.this);
                                changing = true;
                                enabled.setChecked(true);
                                changing = false;
                                refreshSenders();
                                Toast.makeText(ReceiverPairActivity.this,
                                        "接收配对成功", Toast.LENGTH_SHORT).show();
                            } else {
                                if (!ok) connectionStatus.setText(message);
                                handler.postDelayed(poll, 2000);
                            }
                        }
                    });
                }
            });
        }
    };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        if (Build.VERSION.SDK_INT >= 21) {
            getWindow().setStatusBarColor(Ui.SURFACE);
            getWindow().setNavigationBarColor(Ui.SURFACE);
            getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        }
        buildUi();
        refresh();
    }

    @Override protected void onResume() {
        super.onResume();
        if (Prefs.receiveEnabled(this)) ReceiverBridgeService.start(this);
        refresh();
    }

    @Override protected void onDestroy() {
        handler.removeCallbacks(poll);
        super.onDestroy();
    }

    private void buildUi() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(Ui.BG);
        LinearLayout root = Ui.vertical(this);
        root.setPadding(Ui.dp(this, 14), Ui.statusBarInset(this) + Ui.dp(this, 12),
                Ui.dp(this, 14), Ui.dp(this, 24));
        scroll.addView(root, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        LinearLayout header = Ui.row(this);
        Button back = Ui.button(this, "返回", false);
        header.addView(back, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(this, 40)));
        TextView heading = Ui.title(this, "接收通知", 20);
        LinearLayout.LayoutParams headingParams = new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
        headingParams.setMargins(Ui.dp(this, 12), 0, 0, 0);
        header.addView(heading, headingParams);
        root.addView(header);
        back.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { finish(); }
        });

        LinearLayout settings = Ui.section(this);
        LinearLayout receiveRow = Ui.row(this);
        LinearLayout receiveCopy = Ui.vertical(this);
        receiveCopy.addView(Ui.title(this, "允许本机接收", 17));
        TextView receiveHint = Ui.subtitle(this, "与发送功能可同时开启，断网后自动重连");
        receiveHint.setPadding(0, Ui.dp(this, 3), 0, 0);
        receiveCopy.addView(receiveHint);
        receiveRow.addView(receiveCopy, new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        enabled = new Switch(this);
        enabled.setTextColor(Ui.INK);
        receiveRow.addView(enabled);
        settings.addView(receiveRow);
        connectionStatus = Ui.subtitle(this, "未连接");
        connectionStatus.setPadding(0, Ui.dp(this, 10), 0, 0);
        settings.addView(connectionStatus);
        root.addView(settings);

        LinearLayout senderManagement = Ui.section(this);
        senderManagement.addView(Ui.title(this, "管理发送设备", 17));
        TextView senderHint = Ui.subtitle(
                this, "可单独删除某一台发送设备，不影响其他设备或本机配对");
        senderHint.setPadding(0, Ui.dp(this, 4), 0, Ui.dp(this, 8));
        senderManagement.addView(senderHint);
        sendersSummary = Ui.subtitle(this, "正在读取发送设备");
        senderManagement.addView(sendersSummary);
        sendersList = Ui.vertical(this);
        senderManagement.addView(sendersList, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(senderManagement);

        LinearLayout pairing = Ui.section(this);
        pairing.addView(Ui.title(this, "连接一台发送设备", 17));
        TextView hint = Ui.subtitle(this, "在另一台设备输入下方 6 位配对码，或扫描二维码");
        hint.setPadding(0, Ui.dp(this, 4), 0, Ui.dp(this, 10));
        pairing.addView(hint);
        code = Ui.title(this, "尚未生成", 27);
        code.setGravity(Gravity.CENTER);
        pairing.addView(code, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 54)));
        expiry = Ui.subtitle(this, "");
        expiry.setGravity(Gravity.CENTER);
        pairing.addView(expiry);
        qr = new ImageView(this);
        qr.setScaleType(ImageView.ScaleType.FIT_CENTER);
        LinearLayout.LayoutParams qrParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 210));
        qrParams.setMargins(0, Ui.dp(this, 10), 0, Ui.dp(this, 10));
        pairing.addView(qr, qrParams);
        generate = Ui.button(this, "生成配对码", true);
        pairing.addView(generate, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 44)));
        root.addView(pairing);

        LinearLayout privacySection = Ui.section(this);
        privacySection.addView(Ui.title(this, "本机显示", 17));
        TextView privacyHint = Ui.subtitle(this, "最终采用发送端和本机中更严格的设置");
        privacyHint.setPadding(0, Ui.dp(this, 4), 0, Ui.dp(this, 10));
        privacySection.addView(privacyHint);
        privacy = new RadioGroup(this);
        privacy.setOrientation(RadioGroup.HORIZONTAL);
        privacySection.addView(privacy, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 44)));
        addPrivacy(301, "完整", "full", 0);
        addPrivacy(302, "仅标题", "title", Ui.dp(this, 6));
        addPrivacy(303, "仅来源", "source", Ui.dp(this, 6));
        root.addView(privacySection);

        setContentView(scroll);
        enabled.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            @Override public void onCheckedChanged(CompoundButton button, boolean checked) {
                if (changing) return;
                if (checked && requestNotificationPermission()) {
                    changing = true;
                    enabled.setChecked(false);
                    changing = false;
                    return;
                }
                Prefs.setReceiveEnabled(ReceiverPairActivity.this, checked);
                if (checked) {
                    if (Prefs.localReceiverReady(ReceiverPairActivity.this)) {
                        ReceiverBridgeService.start(ReceiverPairActivity.this);
                    } else {
                        generatePairing();
                    }
                    Toast.makeText(ReceiverPairActivity.this,
                            "接收通知已开启", Toast.LENGTH_SHORT).show();
                } else {
                    ReceiverBridgeService.stop(ReceiverPairActivity.this);
                    Toast.makeText(ReceiverPairActivity.this,
                            "接收通知已关闭", Toast.LENGTH_SHORT).show();
                }
                refresh();
            }
        });
        generate.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { generatePairing(); }
        });
        privacy.setOnCheckedChangeListener(new RadioGroup.OnCheckedChangeListener() {
            @Override public void onCheckedChanged(RadioGroup group, int checkedId) {
                if (changing) return;
                View selected = group.findViewById(checkedId);
                if (selected == null || selected.getTag() == null) return;
                Prefs.setReceiveContentMode(ReceiverPairActivity.this,
                        selected.getTag().toString());
                Toast.makeText(ReceiverPairActivity.this,
                        "本机显示设置已保存", Toast.LENGTH_SHORT).show();
            }
        });
    }

    private void addPrivacy(int id, String text, String tag, int left) {
        RadioButton button = new RadioButton(this);
        button.setId(id);
        button.setTag(tag);
        button.setText(text);
        button.setTextSize(13);
        button.setGravity(Gravity.CENTER);
        button.setButtonDrawable(null);
        button.setTextColor(Ui.segmentTextColors());
        button.setBackground(Ui.segmentBackground(this));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.MATCH_PARENT, 1);
        params.setMargins(left, 0, 0, 0);
        privacy.addView(button, params);
    }

    private void refresh() {
        changing = true;
        enabled.setChecked(Prefs.receiveEnabled(this));
        changing = false;
        String mode = Prefs.receiveContentMode(this);
        changing = true;
        for (int index = 0; index < privacy.getChildCount(); index++) {
            View child = privacy.getChildAt(index);
            if (mode.equals(child.getTag())) privacy.check(child.getId());
        }
        changing = false;
        if (!Prefs.localReceiverReady(this)) {
            connectionStatus.setText("尚未连接发送设备");
            connectionStatus.setTextColor(Ui.RED);
        } else {
            String value = ReceiverBridgeService.status();
            connectionStatus.setText(value + " · 密钥 " + Prefs.localReceiverFingerprint(this));
            connectionStatus.setTextColor("服务器在线".equals(value) ? Ui.GREEN : Ui.MUTED);
        }
        refreshSenders();
    }

    private void refreshSenders() {
        if (sendersList == null || sendersSummary == null) return;
        if (!Prefs.localReceiverReady(this)) {
            sendersLoading = false;
            senders = new ArrayList<>();
            sendersSummary.setText("本机尚未建立接收身份");
            sendersSummary.setTextColor(Ui.MUTED);
            renderSenders();
            return;
        }
        if (sendersLoading) return;
        sendersLoading = true;
        sendersSummary.setText("正在读取发送设备");
        sendersSummary.setTextColor(Ui.MUTED);
        ReceiverClient.senders(this, new ReceiverClient.SendersCallback() {
            @Override public void done(
                    final boolean ok, final String message, final JSONArray values) {
                runOnUiThread(new Runnable() {
                    @Override public void run() {
                        sendersLoading = false;
                        if (isFinishing()) return;
                        if (!ok || values == null) {
                            sendersSummary.setText(message == null
                                    ? "读取发送设备失败" : message);
                            sendersSummary.setTextColor(Ui.RED);
                            return;
                        }
                        List<SenderDevice> updated = new ArrayList<>();
                        for (int index = 0; index < values.length(); index++) {
                            JSONObject value = values.optJSONObject(index);
                            if (value == null) continue;
                            try {
                                updated.add(new SenderDevice(
                                        value.optString("deviceId", ""),
                                        value.optString("name", ""),
                                        value.optString("platform", ""),
                                        value.optString("fingerprint", "")));
                            } catch (IllegalArgumentException ignored) {
                                // Ignore malformed rows without affecting known-good devices.
                            }
                        }
                        senders = updated;
                        renderSenders();
                    }
                });
            }
        });
    }

    private void renderSenders() {
        sendersList.removeAllViews();
        if (senders.isEmpty()) {
            sendersSummary.setText("暂无已连接的发送设备");
            sendersSummary.setTextColor(Ui.MUTED);
            return;
        }
        sendersSummary.setText("已连接 " + senders.size() + " 台，可单独删除");
        sendersSummary.setTextColor(Ui.GREEN);
        for (final SenderDevice device : senders) {
            LinearLayout row = Ui.row(this);
            row.setPadding(0, Ui.dp(this, 10), 0, 0);
            LinearLayout details = Ui.vertical(this);
            details.addView(Ui.title(this, device.displayName(), 15));
            String platform = senderPlatform(device.platform);
            String identifier = device.fingerprint.isEmpty()
                    ? platform : platform + " · 设备编号 " + device.fingerprint;
            TextView metadata = Ui.subtitle(this, identifier);
            metadata.setPadding(0, Ui.dp(this, 2), 0, 0);
            details.addView(metadata);
            row.addView(details, new LinearLayout.LayoutParams(
                    0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
            Button remove = Ui.button(this, "删除", false);
            LinearLayout.LayoutParams removeParams = new LinearLayout.LayoutParams(
                    Ui.dp(this, 78), Ui.dp(this, 40));
            removeParams.setMargins(Ui.dp(this, 10), 0, 0, 0);
            row.addView(remove, removeParams);
            remove.setOnClickListener(new View.OnClickListener() {
                @Override public void onClick(View view) { confirmRemoveSender(device); }
            });
            sendersList.addView(row);
        }
    }

    private void confirmRemoveSender(final SenderDevice device) {
        new AlertDialog.Builder(this)
                .setTitle("删除发送设备？")
                .setMessage("确定删除“" + device.displayName()
                        + "”？\n\n只解除这台发送设备与本机的连接，"
                        + "其他发送设备、本机接收身份和已有配对信息都会保留。")
                .setNegativeButton("取消", null)
                .setPositiveButton("删除此设备", new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface dialog, int which) {
                        sendersSummary.setText("正在删除“" + device.displayName() + "”");
                        sendersSummary.setTextColor(Ui.MUTED);
                        ReceiverClient.revokeSender(
                                ReceiverPairActivity.this,
                                device.id,
                                new ReceiverClient.ActionCallback() {
                                    @Override public void done(
                                            final boolean ok, final String message) {
                                        runOnUiThread(new Runnable() {
                                            @Override public void run() {
                                                if (isFinishing()) return;
                                                if (!ok) {
                                                    sendersSummary.setText(message == null
                                                            ? "删除失败，原连接已保留" : message);
                                                    sendersSummary.setTextColor(Ui.RED);
                                                    return;
                                                }
                                                senders = SenderDevices.without(
                                                        senders, device.id);
                                                renderSenders();
                                                Toast.makeText(
                                                        ReceiverPairActivity.this,
                                                        "已删除“" + device.displayName() + "”",
                                                        Toast.LENGTH_SHORT).show();
                                            }
                                        });
                                    }
                                });
                    }
                })
                .show();
    }

    private static String senderPlatform(String value) {
        if ("android".equals(value)) return "Android";
        if ("ios".equals(value)) return "iPhone";
        if ("macos".equals(value)) return "Mac";
        if ("windows".equals(value)) return "Windows";
        return "发送设备";
    }

    private void generatePairing() {
        if (requestNotificationPermission()) return;
        generate.setEnabled(false);
        connectionStatus.setText("正在生成安全配对码");
        connectionStatus.setTextColor(Ui.MUTED);
        ReceiverClient.startPairing(this, new ReceiverClient.PairingCallback() {
            @Override public void done(final boolean ok, final String message, final JSONObject pairing) {
                runOnUiThread(new Runnable() {
                    @Override public void run() {
                        if (isFinishing()) return;
                        generate.setEnabled(true);
                        if (!ok || pairing == null) {
                            connectionStatus.setText(message);
                            connectionStatus.setTextColor(Ui.RED);
                            return;
                        }
                        Prefs.setReceiveEnabled(ReceiverPairActivity.this, true);
                        changing = true;
                        enabled.setChecked(true);
                        changing = false;
                        pairingId = pairing.optString("pairingId", "");
                        expiresAt = pairing.optLong("expiresAt", 0L);
                        code.setText(formatCode(pairing.optString("code", "")));
                        qr.setImageBitmap(qrBitmap(pairing.optString("qrPayload", "")));
                        connectionStatus.setText("等待另一台设备连接");
                        connectionStatus.setTextColor(Ui.MUTED);
                        generate.setText("重新生成配对码");
                        handler.removeCallbacks(poll);
                        handler.post(poll);
                    }
                });
            }
        });
    }

    private void refreshExpiry() {
        long seconds = Math.max(0, (expiresAt - System.currentTimeMillis()) / 1000L);
        expiry.setText(seconds + " 秒后失效 · 密钥 " + Prefs.localReceiverFingerprint(this));
        expiry.setTextColor(Ui.MUTED);
    }

    private static String formatCode(String value) {
        return value.length() == 6 ? value.substring(0, 3) + " " + value.substring(3) : value;
    }

    private static Bitmap qrBitmap(String value) {
        if (value == null || value.isEmpty()) return null;
        try {
            BitMatrix matrix = new MultiFormatWriter().encode(
                    value, BarcodeFormat.QR_CODE, 420, 420);
            Bitmap bitmap = Bitmap.createBitmap(420, 420, Bitmap.Config.ARGB_8888);
            for (int y = 0; y < 420; y++) {
                for (int x = 0; x < 420; x++) {
                    bitmap.setPixel(x, y, matrix.get(x, y) ? Color.BLACK : Color.WHITE);
                }
            }
            return bitmap;
        } catch (Exception ignored) {
            return null;
        }
    }

    private boolean requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 906);
            return true;
        }
        return false;
    }

    @Override public void onRequestPermissionsResult(
            int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != 906) return;
        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            generatePairing();
        } else {
            connectionStatus.setText("需要通知权限才能显示接收内容");
            connectionStatus.setTextColor(Ui.RED);
        }
    }
}
