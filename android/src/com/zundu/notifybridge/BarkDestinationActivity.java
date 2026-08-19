package com.zundu.notifybridge;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Base64;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public class BarkDestinationActivity extends Activity {
    private static final long POLL_INTERVAL_MS = 2000;
    private static final long POLL_WINDOW_MS = 5 * 60 * 1000;
    private static final int MAX_QR_BASE64_LENGTH = 128 * 1024;
    private static final int MAX_QR_BYTES = 96 * 1024;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final List<BarkDestination> destinations = new ArrayList<>();
    private final Set<String> enrollmentBaseline = new HashSet<>();
    private LinearLayout destinationList;
    private TextView listStatus;
    private TextView enrollmentStatus;
    private Button addButton;
    private Button refreshButton;
    private AlertDialog enrollmentDialog;
    private long enrollmentDeadline;
    private boolean destinationsLoading;
    private boolean stopped;

    private final Runnable enrollmentPoll = new Runnable() {
        @Override public void run() { requestDestinations(true); }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Ui.SURFACE);
        getWindow().setNavigationBarColor(Ui.SURFACE);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        buildUi();
    }

    @Override
    protected void onResume() {
        super.onResume();
        stopped = false;
        if (!Prefs.paired(this)) {
            Toast.makeText(this, "请先建立发送身份", Toast.LENGTH_SHORT).show();
            finish();
            return;
        }
        requestDestinations(false);
        if (enrollmentDialog != null && enrollmentDialog.isShowing()) {
            scheduleEnrollmentPoll(300);
        }
    }

    @Override
    protected void onStop() {
        stopped = true;
        handler.removeCallbacks(enrollmentPoll);
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        stopEnrollmentPolling();
        if (enrollmentDialog != null) enrollmentDialog.dismiss();
        super.onDestroy();
    }

    private void buildUi() {
        LinearLayout root = Ui.vertical(this);
        root.setBackgroundColor(Ui.BG);

        LinearLayout bar = Ui.row(this);
        bar.setPadding(
                Ui.dp(this, 10), Ui.statusBarInset(this) + Ui.dp(this, 10),
                Ui.dp(this, 14), Ui.dp(this, 10));
        bar.setBackgroundColor(Ui.SURFACE);
        Button back = Ui.button(this, "返回", false);
        bar.addView(back, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(this, 44)));
        TextView heading = Ui.title(this, "管理 iPhone", 19);
        LinearLayout.LayoutParams headingParams = new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
        headingParams.setMargins(Ui.dp(this, 12), 0, 0, 0);
        bar.addView(heading, headingParams);
        root.addView(bar);

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout content = Ui.vertical(this);
        content.setPadding(Ui.dp(this, 14), Ui.dp(this, 16), Ui.dp(this, 14), Ui.dp(this, 24));
        scroll.addView(content, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(scroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));

        LinearLayout introduction = Ui.section(this);
        introduction.addView(Ui.title(this, "iPhone（Bark）", 17));
        TextView explanation = Ui.subtitle(this,
                "让 iPhone 通过 Bark 接收这台 Android 转发的通知。绑定信息由服务器安全保管，本机不会显示 Bark Key。");
        explanation.setPadding(0, Ui.dp(this, 5), 0, 0);
        introduction.addView(explanation);
        content.addView(introduction);

        LinearLayout management = Ui.section(this);
        LinearLayout titleRow = Ui.row(this);
        titleRow.addView(Ui.title(this, "已连接的 iPhone", 17),
                new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        refreshButton = Ui.button(this, "刷新", false);
        titleRow.addView(refreshButton, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(this, 44)));
        management.addView(titleRow);
        listStatus = Ui.subtitle(this, "正在读取");
        listStatus.setPadding(0, Ui.dp(this, 6), 0, Ui.dp(this, 4));
        management.addView(listStatus);
        destinationList = Ui.vertical(this);
        management.addView(destinationList, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        content.addView(management);

        addButton = Ui.button(this, "添加 iPhone", true);
        addButton.setEnabled(false);
        content.addView(addButton, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 48)));
        TextView addHint = Ui.subtitle(this,
                "需要在 iPhone 安装 Bark。绑定二维码和备用码有效期为 5 分钟。");
        addHint.setPadding(Ui.dp(this, 4), Ui.dp(this, 8), Ui.dp(this, 4), 0);
        content.addView(addHint);

        setContentView(root);
        back.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { finish(); }
        });
        refreshButton.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { requestDestinations(false); }
        });
        addButton.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { beginEnrollment(); }
        });
    }

    private void requestDestinations(final boolean polling) {
        if (stopped && polling) return;
        if (destinationsLoading) {
            if (polling) scheduleEnrollmentPoll(700);
            return;
        }
        destinationsLoading = true;
        if (!polling) {
            refreshButton.setEnabled(false);
            addButton.setEnabled(false);
            listStatus.setText("正在读取已连接的 iPhone");
            listStatus.setTextColor(Ui.MUTED);
        }
        PairingClient.destinations(getApplicationContext(),
                new PairingClient.DestinationsCallback() {
                    @Override
                    public void done(final boolean ok, final String message, final JSONArray values) {
                        runOnUiThread(new Runnable() {
                            @Override public void run() {
                                destinationsLoading = false;
                                if (isFinishing() || isDestroyed()) return;
                                refreshButton.setEnabled(true);
                                if (!ok || values == null) {
                                    if (polling) {
                                        setEnrollmentStatus("暂时无法确认绑定，将自动重试", false);
                                        scheduleEnrollmentPoll(POLL_INTERVAL_MS);
                                    } else {
                                        if (destinations.isEmpty()) renderDestinations();
                                        listStatus.setText(message == null
                                                ? "读取失败，请点击刷新重试" : message);
                                        listStatus.setTextColor(Ui.RED);
                                    }
                                    return;
                                }
                                addButton.setEnabled(true);
                                List<BarkDestination> updated = parseDestinations(values);
                                String addedId = polling ? newDestinationId(updated) : "";
                                destinations.clear();
                                destinations.addAll(updated);
                                renderDestinations();
                                if (polling && !addedId.isEmpty()) {
                                    stopEnrollmentPolling();
                                    if (enrollmentDialog != null) enrollmentDialog.dismiss();
                                    Toast.makeText(BarkDestinationActivity.this,
                                            "iPhone 已连接", Toast.LENGTH_SHORT).show();
                                } else if (polling) {
                                    setEnrollmentStatus("等待 iPhone 完成绑定…", true);
                                    scheduleEnrollmentPoll(POLL_INTERVAL_MS);
                                }
                            }
                        });
                    }
                });
    }

    private List<BarkDestination> parseDestinations(JSONArray values) {
        List<BarkDestination> parsed = new ArrayList<>();
        for (int index = 0; index < values.length(); index++) {
            JSONObject value = values.optJSONObject(index);
            if (value == null) continue;
            BarkDestination destination = BarkDestination.fromFields(
                    value.optString("type", ""),
                    value.optString("destinationId", ""),
                    value.optString("name", ""),
                    value.optString("fingerprint", ""),
                    value.optLong("lastSuccessAt", 0),
                    value.optLong("lastFailureAt", 0));
            if (destination != null) parsed.add(destination);
        }
        return parsed;
    }

    private void renderDestinations() {
        destinationList.removeAllViews();
        if (destinations.isEmpty()) {
            listStatus.setText("尚未添加 iPhone");
            listStatus.setTextColor(Ui.MUTED);
            TextView empty = Ui.subtitle(this, "点击下方“添加 iPhone”开始绑定");
            empty.setGravity(Gravity.CENTER);
            empty.setPadding(Ui.dp(this, 12), Ui.dp(this, 18),
                    Ui.dp(this, 12), Ui.dp(this, 18));
            empty.setBackground(Ui.background(this, Ui.BG, Ui.LINE, 7));
            destinationList.addView(empty, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
            return;
        }
        listStatus.setText("已连接 " + destinations.size() + " 台，可单独测试或移除");
        listStatus.setTextColor(Ui.GREEN);
        for (final BarkDestination destination : destinations) {
            destinationList.addView(destinationCard(destination));
        }
    }

    private View destinationCard(final BarkDestination destination) {
        LinearLayout card = Ui.vertical(this);
        card.setPadding(Ui.dp(this, 12), Ui.dp(this, 11), Ui.dp(this, 12), Ui.dp(this, 11));
        card.setBackground(Ui.background(this, Ui.BG, Ui.LINE, 7));
        LinearLayout.LayoutParams cardParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        cardParams.setMargins(0, Ui.dp(this, 7), 0, 0);
        card.setLayoutParams(cardParams);

        card.addView(Ui.title(this, destination.name, 15));
        TextView state = Ui.subtitle(this, destination.deliveryState());
        state.setTextColor(destination.lastFailureAt > destination.lastSuccessAt
                ? Ui.RED : Ui.GREEN);
        state.setPadding(0, Ui.dp(this, 3), 0, 0);
        card.addView(state);
        if (!destination.fingerprint.isEmpty()) {
            TextView identity = Ui.subtitle(this, "设备标识 " + destination.fingerprint);
            identity.setPadding(0, Ui.dp(this, 2), 0, 0);
            card.addView(identity);
        }

        LinearLayout actions = Ui.row(this);
        LinearLayout.LayoutParams actionParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        actionParams.setMargins(0, Ui.dp(this, 9), 0, 0);
        card.addView(actions, actionParams);
        final Button test = Ui.button(this, "发送测试", false);
        Button remove = Ui.button(this, "移除", false);
        actions.addView(test, weighted(1, 0, 44));
        actions.addView(remove, weighted(1, Ui.dp(this, 8), 44));
        test.setContentDescription("向" + destination.name + "发送测试通知");
        remove.setContentDescription("移除" + destination.name);
        test.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { sendTest(destination, test); }
        });
        remove.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { confirmRemove(destination); }
        });
        return card;
    }

    private LinearLayout.LayoutParams weighted(int weight, int left, int height) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                0, Ui.dp(this, height), weight);
        params.setMargins(left, 0, 0, 0);
        return params;
    }

    private void beginEnrollment() {
        if (destinationsLoading || !addButton.isEnabled()) {
            Toast.makeText(this, "请等待接收设备读取完成", Toast.LENGTH_SHORT).show();
            return;
        }
        addButton.setEnabled(false);
        listStatus.setText("正在生成安全绑定码");
        listStatus.setTextColor(Ui.MUTED);
        PairingClient.startBarkEnrollment(getApplicationContext(),
                new PairingClient.BarkEnrollmentCallback() {
                    @Override
                    public void done(final boolean ok, final String message,
                                     final JSONObject enrollment) {
                        runOnUiThread(new Runnable() {
                            @Override public void run() {
                                if (isFinishing() || isDestroyed()) return;
                                addButton.setEnabled(true);
                                if (!ok || enrollment == null) {
                                    listStatus.setText(message == null
                                            ? "无法生成绑定码，请稍后重试" : message);
                                    listStatus.setTextColor(Ui.RED);
                                    return;
                                }
                                try {
                                    showEnrollment(enrollment);
                                } catch (IllegalArgumentException invalid) {
                                    listStatus.setText("服务器返回的绑定码无效，请稍后重试");
                                    listStatus.setTextColor(Ui.RED);
                                }
                            }
                        });
                    }
                });
    }

    private void showEnrollment(JSONObject enrollment) {
        String code = enrollment.optString("code", "").trim();
        if (!code.matches("[0-9]{6}")) throw new IllegalArgumentException("invalid code");
        Bitmap qr = decodeQr(enrollment.optString("qrPng", ""));
        long serverExpiry = enrollment.optLong("expiresAt", 0);
        long maximumDeadline = System.currentTimeMillis() + POLL_WINDOW_MS;
        enrollmentDeadline = serverExpiry > System.currentTimeMillis()
                ? Math.min(serverExpiry, maximumDeadline) : maximumDeadline;
        enrollmentBaseline.clear();
        for (BarkDestination destination : destinations) {
            enrollmentBaseline.add(destination.id);
        }

        LinearLayout content = Ui.vertical(this);
        content.setPadding(Ui.dp(this, 22), Ui.dp(this, 10), Ui.dp(this, 22), Ui.dp(this, 4));
        ImageView image = new ImageView(this);
        image.setImageBitmap(qr);
        image.setScaleType(ImageView.ScaleType.FIT_CENTER);
        image.setContentDescription("iPhone Bark 绑定二维码");
        content.addView(image, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 236)));
        TextView instruction = Ui.subtitle(this,
                "用 iPhone 相机扫描二维码并按页面提示完成 Bark 绑定。扫码不便时，可在绑定页输入备用码：");
        instruction.setPadding(0, Ui.dp(this, 8), 0, Ui.dp(this, 6));
        content.addView(instruction);
        TextView codeView = Ui.title(this, code, 30);
        codeView.setGravity(Gravity.CENTER);
        codeView.setContentDescription("六位备用码 " + code);
        codeView.setPadding(0, Ui.dp(this, 6), 0, Ui.dp(this, 6));
        codeView.setBackground(Ui.background(this, Ui.BG, Ui.LINE, 7));
        content.addView(codeView, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 58)));
        TextView expiry = Ui.subtitle(this, "二维码和备用码将在 5 分钟内失效");
        expiry.setGravity(Gravity.CENTER);
        expiry.setPadding(0, Ui.dp(this, 8), 0, 0);
        content.addView(expiry);
        enrollmentStatus = Ui.subtitle(this, "等待 iPhone 完成绑定…");
        enrollmentStatus.setGravity(Gravity.CENTER);
        enrollmentStatus.setPadding(0, Ui.dp(this, 8), 0, 0);
        content.addView(enrollmentStatus);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(content, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        enrollmentDialog = new AlertDialog.Builder(this)
                .setTitle("添加 iPhone")
                .setView(scroll)
                .setNegativeButton("关闭", null)
                .create();
        enrollmentDialog.setOnDismissListener(new DialogInterface.OnDismissListener() {
            @Override public void onDismiss(DialogInterface dialog) { stopEnrollmentPolling(); }
        });
        enrollmentDialog.show();
        scheduleEnrollmentPoll(800);
    }

    private Bitmap decodeQr(String encoded) {
        if (encoded == null || encoded.isEmpty() || encoded.length() > MAX_QR_BASE64_LENGTH) {
            throw new IllegalArgumentException("invalid qr");
        }
        try {
            byte[] data = Base64.decode(encoded, Base64.DEFAULT);
            if (data.length < 8 || data.length > MAX_QR_BYTES) {
                throw new IllegalArgumentException("invalid qr size");
            }
            boolean png = data[0] == (byte) 0x89 && data[1] == 'P' && data[2] == 'N'
                    && data[3] == 'G' && data[4] == 0x0d && data[5] == 0x0a
                    && data[6] == 0x1a && data[7] == 0x0a;
            if (!png) throw new IllegalArgumentException("invalid qr format");
            Bitmap bitmap = BitmapFactory.decodeByteArray(data, 0, data.length);
            if (bitmap == null || bitmap.getWidth() > 2048 || bitmap.getHeight() > 2048) {
                throw new IllegalArgumentException("invalid qr bitmap");
            }
            return bitmap;
        } catch (IllegalArgumentException invalid) {
            throw invalid;
        } catch (Exception invalid) {
            throw new IllegalArgumentException("invalid qr", invalid);
        }
    }

    private String newDestinationId(List<BarkDestination> updated) {
        for (BarkDestination destination : updated) {
            if (!enrollmentBaseline.contains(destination.id)) return destination.id;
        }
        return "";
    }

    private void scheduleEnrollmentPoll(long delay) {
        handler.removeCallbacks(enrollmentPoll);
        if (stopped || enrollmentDialog == null || !enrollmentDialog.isShowing()) return;
        if (System.currentTimeMillis() >= enrollmentDeadline) {
            setEnrollmentStatus("绑定码已过期，请关闭后重新生成", false);
            return;
        }
        handler.postDelayed(enrollmentPoll, Math.max(250, delay));
    }

    private void stopEnrollmentPolling() {
        handler.removeCallbacks(enrollmentPoll);
        enrollmentDeadline = 0;
        enrollmentStatus = null;
    }

    private void setEnrollmentStatus(String value, boolean ok) {
        if (enrollmentStatus == null) return;
        enrollmentStatus.setText(value);
        enrollmentStatus.setTextColor(ok ? Ui.MUTED : Ui.RED);
    }

    private void sendTest(final BarkDestination destination, final Button button) {
        button.setEnabled(false);
        listStatus.setText("正在向“" + destination.name + "”发送测试通知");
        listStatus.setTextColor(Ui.MUTED);
        PairingClient.testBark(getApplicationContext(), destination.id,
                new PairingClient.ActionCallback() {
                    @Override public void done(final boolean ok, final String message) {
                        runOnUiThread(new Runnable() {
                            @Override public void run() {
                                if (isFinishing() || isDestroyed()) return;
                                button.setEnabled(true);
                                listStatus.setText(message == null
                                        ? (ok ? "测试通知已发送" : "测试失败，请重试") : message);
                                listStatus.setTextColor(ok ? Ui.GREEN : Ui.RED);
                                if (ok) requestDestinations(false);
                            }
                        });
                    }
                });
    }

    private void confirmRemove(final BarkDestination destination) {
        new AlertDialog.Builder(this)
                .setTitle("移除这台 iPhone？")
                .setMessage("将停止向“" + destination.name
                        + "”转发通知，其他接收设备不会受影响。")
                .setNegativeButton("取消", null)
                .setPositiveButton("移除此设备", new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface dialog, int which) {
                        revoke(destination);
                    }
                })
                .show();
    }

    private void revoke(final BarkDestination destination) {
        listStatus.setText("正在移除“" + destination.name + "”");
        listStatus.setTextColor(Ui.MUTED);
        PairingClient.revokeBark(getApplicationContext(), destination.id,
                new PairingClient.ActionCallback() {
                    @Override public void done(final boolean ok, final String message) {
                        runOnUiThread(new Runnable() {
                            @Override public void run() {
                                if (isFinishing() || isDestroyed()) return;
                                if (!ok) {
                                    listStatus.setText(message == null
                                            ? "移除失败，请重试" : message);
                                    listStatus.setTextColor(Ui.RED);
                                    return;
                                }
                                Toast.makeText(BarkDestinationActivity.this,
                                        "已移除“" + destination.name + "”",
                                        Toast.LENGTH_SHORT).show();
                                requestDestinations(false);
                            }
                        });
                    }
                });
    }
}
