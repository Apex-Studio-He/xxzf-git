package com.zundu.notifybridge;

import android.app.Activity;
import android.app.AlertDialog;
import android.Manifest;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
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

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

public class MainActivity extends Activity {
    private TextView connectionStatus;
    private TextView receiverSummary;
    private TextView serverStatus;
    private Button recoverPairing;
    private TextView appsSummary;
    private TextView listenerSummary;
    private TextView backgroundSummary;
    private Button listenerButton;
    private Button backgroundButton;
    private TextView testResult;
    private TextView updateStatus;
    private Button updateButton;
    private TextView receiveStatus;
    private Switch enabled;
    private RadioGroup privacy;
    private boolean refreshing;
    private boolean credentialRecoveryRequired;
    private boolean startupUpdateCheckStarted;
    private boolean pendingUpdatePromptShown;
    private boolean listenerRepairAttempted;
    private boolean listenerRepairInProgress;
    private final Handler statusHandler = new Handler(Looper.getMainLooper());
    private final Runnable listenerRepairRefresh = new Runnable() {
        @Override public void run() {
            refreshListenerStatus();
        }
    };
    private final Runnable listenerRepairFinish = new Runnable() {
        @Override public void run() {
            listenerRepairInProgress = false;
            refreshListenerStatus();
        }
    };
    private final Runnable statusRefresh = new Runnable() {
        @Override public void run() {
            refreshServerStatus();
            ListenerBinding.ensure(MainActivity.this);
            refreshListenerStatus();
            refreshBackgroundStatus();
            statusHandler.postDelayed(this, 15000);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= 21) {
            getWindow().setStatusBarColor(Ui.SURFACE);
            getWindow().setNavigationBarColor(Ui.SURFACE);
            getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        }
        buildUi();
    }

    @Override
    protected void onResume() {
        super.onResume();
        listenerRepairInProgress = false;
        BackgroundRecovery.restore(this);
        refreshing = true;
        enabled.setChecked(Prefs.enabled(this));
        refreshing = false;
        refresh();
        statusHandler.removeCallbacks(statusRefresh);
        statusHandler.post(statusRefresh);
        if (UpdateManager.hasPendingUpdate(this)) {
            offerPendingUpdate();
        } else {
            pendingUpdatePromptShown = false;
            boolean requestedFromNotification = getIntent().getBooleanExtra(
                    UpdateManager.EXTRA_SHOW_UPDATE, false);
            getIntent().removeExtra(UpdateManager.EXTRA_SHOW_UPDATE);
            if (requestedFromNotification || !startupUpdateCheckStarted) {
                startupUpdateCheckStarted = true;
                checkForUpdates(requestedFromNotification);
            }
        }
    }

    @Override
    protected void onPause() {
        statusHandler.removeCallbacks(statusRefresh);
        statusHandler.removeCallbacks(listenerRepairRefresh);
        statusHandler.removeCallbacks(listenerRepairFinish);
        super.onPause();
    }

    private void buildUi() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(Ui.BG);
        LinearLayout root = Ui.vertical(this);
        root.setPadding(
                Ui.dp(this, 14),
                Ui.statusBarInset(this) + Ui.dp(this, 12),
                Ui.dp(this, 14),
                Ui.dp(this, 24));
        scroll.addView(root, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        root.addView(buildHeader());
        root.addView(buildForwardingSection());
        root.addView(buildReceivingSection());
        root.addView(buildPrivacySection());
        root.addView(buildPermissionSection());
        root.addView(buildUpdateSection());
        root.addView(buildDiagnosticsSection());
        setContentView(scroll);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (intent.getBooleanExtra(UpdateManager.EXTRA_SHOW_UPDATE, false)) {
            intent.removeExtra(UpdateManager.EXTRA_SHOW_UPDATE);
            startupUpdateCheckStarted = true;
            checkForUpdates(true);
        }
    }

    private View buildHeader() {
        LinearLayout header = Ui.row(this);
        header.setPadding(Ui.dp(this, 6), Ui.dp(this, 8), Ui.dp(this, 6), Ui.dp(this, 18));
        ImageView logo = new ImageView(this);
        logo.setImageResource(com.zundu.notifybridge.R.drawable.ic_launcher);
        logo.setScaleType(ImageView.ScaleType.FIT_CENTER);
        header.addView(logo, new LinearLayout.LayoutParams(Ui.dp(this, 46), Ui.dp(this, 46)));

        LinearLayout copy = Ui.vertical(this);
        LinearLayout.LayoutParams copyParams = new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
        copyParams.setMargins(Ui.dp(this, 12), 0, Ui.dp(this, 10), 0);
        header.addView(copy, copyParams);
        copy.addView(Ui.title(this, "转发", 23));
        TextView subtitle = Ui.subtitle(this, "发送与接收通知");
        subtitle.setPadding(0, Ui.dp(this, 2), 0, 0);
        copy.addView(subtitle);
        serverStatus = Ui.subtitle(this, "正在检查服务器");
        serverStatus.setTextSize(12);
        serverStatus.setPadding(0, Ui.dp(this, 2), 0, 0);
        copy.addView(serverStatus);

        connectionStatus = Ui.status(this, "未连接", false);
        header.addView(connectionStatus);
        return header;
    }

    private View buildForwardingSection() {
        LinearLayout section = Ui.section(this);
        LinearLayout top = Ui.row(this);
        top.addView(Ui.title(this, "发送设置", 17), new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        enabled = new Switch(this);
        enabled.setText("启用");
        enabled.setTextColor(Ui.INK);
        enabled.setTextSize(14);
        top.addView(enabled);
        section.addView(top);

        LinearLayout receiver = settingRow("发送到");
        receiverSummary = Ui.subtitle(this, "尚未配对");
        receiverSummary.setMaxLines(2);
        receiver.addView(receiverSummary, new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        Button pair = Ui.button(this, "管理", false);
        receiver.addView(pair, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(this, 40)));
        section.addView(receiver);

        LinearLayout iphone = settingRow("iPhone（Bark）");
        TextView iphoneSummary = Ui.subtitle(this, "只显示来源应用和通知标题，不发送正文");
        iphoneSummary.setMaxLines(2);
        iphone.addView(iphoneSummary, new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        Button manageIphone = Ui.button(this, "连接 / 管理", true);
        iphone.addView(manageIphone, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(this, 40)));
        section.addView(iphone);

        recoverPairing = Ui.button(this, "凭据失效？重新配对", false);
        recoverPairing.setVisibility(View.GONE);
        LinearLayout.LayoutParams recoverParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 42));
        recoverParams.setMargins(0, Ui.dp(this, 10), 0, 0);
        section.addView(recoverPairing, recoverParams);

        LinearLayout apps = settingRow("转发应用");
        appsSummary = Ui.subtitle(this, "全部应用");
        apps.addView(appsSummary, new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        Button choose = Ui.button(this, "选择", false);
        apps.addView(choose, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(this, 40)));
        section.addView(apps);

        Button test = Ui.button(this, "发送测试通知", true);
        LinearLayout.LayoutParams testParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 46));
        testParams.setMargins(0, Ui.dp(this, 12), 0, 0);
        section.addView(test, testParams);
        testResult = Ui.subtitle(this, "");
        testResult.setPadding(0, Ui.dp(this, 8), 0, 0);
        section.addView(testResult);

        enabled.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            @Override public void onCheckedChanged(CompoundButton button, boolean checked) {
                if (refreshing) return;
                Prefs.get(MainActivity.this).edit().putBoolean(Prefs.KEY_ENABLED, checked).apply();
                Toast.makeText(MainActivity.this,
                        checked ? "设置成功：已开启转发" : "设置成功：已暂停转发",
                        Toast.LENGTH_SHORT).show();
            }
        });
        pair.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                startActivity(new Intent(MainActivity.this, PairActivity.class));
            }
        });
        manageIphone.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                if (Prefs.paired(MainActivity.this)) {
                    startActivity(new Intent(
                            MainActivity.this, BarkDestinationActivity.class));
                    return;
                }
                new AlertDialog.Builder(MainActivity.this)
                        .setTitle("先连接通知服务")
                        .setMessage("连接服务器后即可添加 iPhone。Bark 密钥只会保存在服务器，不会保存在这台 Android。")
                        .setNegativeButton("取消", null)
                        .setPositiveButton("去连接", new DialogInterface.OnClickListener() {
                            @Override public void onClick(DialogInterface dialog, int which) {
                                startActivity(new Intent(
                                        MainActivity.this, PairActivity.class));
                            }
                        })
                        .show();
            }
        });
        recoverPairing.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                CredentialRecovery.confirmAndClear(MainActivity.this, new Runnable() {
                    @Override public void run() {
                        credentialRecoveryRequired = false;
                        recoverPairing.setVisibility(View.GONE);
                        refresh();
                        startActivity(new Intent(MainActivity.this, PairActivity.class));
                    }
                });
            }
        });
        choose.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                startActivity(new Intent(MainActivity.this, AppPickerActivity.class));
            }
        });
        test.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { sendTest(); }
        });
        return section;
    }

    private View buildReceivingSection() {
        LinearLayout section = Ui.section(this);
        section.addView(Ui.title(this, "接收设置", 17));
        TextView hint = Ui.subtitle(this, "本机可同时发送和接收，接收通道断网后自动重连");
        hint.setPadding(0, Ui.dp(this, 4), 0, Ui.dp(this, 8));
        section.addView(hint);
        LinearLayout row = settingRow("接收通知");
        receiveStatus = Ui.subtitle(this, "尚未配置");
        row.addView(receiveStatus, new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        Button manage = Ui.button(this, "管理", false);
        row.addView(manage, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(this, 40)));
        section.addView(row);
        manage.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                startActivity(new Intent(MainActivity.this, ReceiverPairActivity.class));
            }
        });
        return section;
    }

    private View buildPrivacySection() {
        LinearLayout section = Ui.section(this);
        section.addView(Ui.title(this, "发送内容", 17));
        privacy = new RadioGroup(this);
        privacy.setOrientation(RadioGroup.HORIZONTAL);
        LinearLayout.LayoutParams privacyParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 44));
        privacyParams.setMargins(0, Ui.dp(this, 10), 0, 0);
        section.addView(privacy, privacyParams);
        addPrivacyOption(201, "完整", "full", 0);
        addPrivacyOption(202, "仅标题", "title", Ui.dp(this, 6));
        addPrivacyOption(203, "仅来源", "source", Ui.dp(this, 6));
        String selected = Prefs.privacy(this);
        for (int index = 0; index < privacy.getChildCount(); index++) {
            View child = privacy.getChildAt(index);
            if (selected.equals(child.getTag())) privacy.check(child.getId());
        }
        privacy.setOnCheckedChangeListener(new RadioGroup.OnCheckedChangeListener() {
            @Override
            public void onCheckedChanged(RadioGroup group, int checkedId) {
                View selectedView = group.findViewById(checkedId);
                if (selectedView != null && selectedView.getTag() != null) {
                    String mode = selectedView.getTag().toString();
                    Prefs.get(MainActivity.this).edit()
                            .putString(Prefs.KEY_PRIVACY, mode)
                            .apply();
                    String message = "full".equals(mode)
                            ? "设置成功：显示标题和正文"
                            : "title".equals(mode)
                            ? "设置成功：仅显示标题"
                            : "设置成功：仅显示来源 App";
                    Toast.makeText(MainActivity.this, message, Toast.LENGTH_SHORT).show();
                }
            }
        });
        return section;
    }

    private View buildPermissionSection() {
        LinearLayout section = Ui.section(this);
        section.addView(Ui.title(this, "系统权限", 17));

        LinearLayout listener = settingRow("读取通知");
        listenerSummary = Ui.subtitle(this, "检查中");
        listener.addView(listenerSummary, new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        listenerButton = Ui.button(this, "设置", false);
        listener.addView(listenerButton, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(this, 40)));
        section.addView(listener);

        LinearLayout battery = settingRow("后台运行");
        backgroundSummary = Ui.subtitle(this, "检查中");
        battery.addView(backgroundSummary, new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        backgroundButton = Ui.button(this, "设置", false);
        battery.addView(backgroundButton, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(this, 40)));
        section.addView(battery);

        listenerButton.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                if (!ListenerBinding.isAccessEnabled(MainActivity.this)) {
                    startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS));
                    return;
                }
                int health = ListenerHealth.state(
                        true,
                        NotifyBridgeService.isRunning(),
                        ListenerBinding.isConnected());
                if (health == ListenerHealth.WAITING) {
                    if (listenerRepairInProgress) return;
                    if (listenerRepairAttempted) {
                        startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS));
                        return;
                    }
                    listenerRepairAttempted = true;
                    listenerRepairInProgress = true;
                    ListenerBinding.forceRepair(MainActivity.this);
                    listenerSummary.setText("正在请求系统重连");
                    listenerSummary.setTextColor(Ui.MUTED);
                    listenerButton.setText("重连中");
                    listenerButton.setEnabled(false);
                    Toast.makeText(MainActivity.this, "正在重新连接通知服务", Toast.LENGTH_SHORT).show();
                    statusHandler.postDelayed(listenerRepairRefresh, 1500);
                    statusHandler.postDelayed(listenerRepairRefresh, 3500);
                    statusHandler.postDelayed(listenerRepairFinish, 7000);
                    return;
                }
                startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS));
            }
        });
        backgroundButton.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { openBackgroundSettings(); }
        });
        return section;
    }

    private View buildDiagnosticsSection() {
        LinearLayout section = Ui.section(this);
        section.addView(Ui.title(this, "诊断", 17));
        TextView privacy = Ui.subtitle(this, "仅上传连接状态和错误代码，不包含通知正文或设备识别信息");
        privacy.setPadding(0, Ui.dp(this, 4), 0, Ui.dp(this, 10));
        section.addView(privacy);
        final Button upload = Ui.button(this, "上传诊断日志", false);
        section.addView(upload, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 44)));
        final TextView result = Ui.subtitle(this, "");
        result.setPadding(0, Ui.dp(this, 8), 0, 0);
        section.addView(result);
        upload.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                upload.setEnabled(false);
                result.setText("正在安全上传");
                ServerClient.uploadDiagnostics(MainActivity.this, new ServerClient.UploadCallback() {
                    @Override public void done(final boolean ok, final String message, final String diagnosticId) {
                        runOnUiThread(new Runnable() {
                            @Override public void run() {
                                upload.setEnabled(true);
                                result.setText(ok ? message + " · 诊断编号 " + diagnosticId : message);
                                result.setTextColor(ok ? Ui.GREEN : Ui.RED);
                                Toast.makeText(MainActivity.this, ok ? "诊断日志上传成功" : message, Toast.LENGTH_SHORT).show();
                            }
                        });
                    }
                });
            }
        });
        return section;
    }

    private View buildUpdateSection() {
        LinearLayout section = Ui.section(this);
        section.addView(Ui.title(this, "软件更新", 17));
        TextView version = Ui.subtitle(this, "当前版本 " + UpdateManager.currentVersionName(this));
        version.setPadding(0, Ui.dp(this, 4), 0, 0);
        section.addView(version);
        updateStatus = Ui.subtitle(this, "启动时自动检查，后台每 6 小时检查一次");
        updateStatus.setPadding(0, Ui.dp(this, 4), 0, Ui.dp(this, 10));
        section.addView(updateStatus);
        updateButton = Ui.button(this, "检查更新", false);
        section.addView(updateButton, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 44)));
        updateButton.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                if (!requestUpdateNotificationPermission()) checkForUpdates(true);
            }
        });
        return section;
    }

    private void checkForUpdates(final boolean manual) {
        if (updateButton == null) return;
        updateButton.setEnabled(false);
        updateStatus.setText("正在安全检查更新");
        updateStatus.setTextColor(Ui.MUTED);
        UpdateManager.check(this, manual, new UpdateManager.Callback() {
            @Override public void done(final UpdateManager.Result result) {
                runOnUiThread(new Runnable() {
                    @Override public void run() {
                        updateButton.setEnabled(true);
                        updateStatus.setText(result.message);
                        updateStatus.setTextColor(result.status == UpdateManager.ERROR
                                ? Ui.RED : result.status == UpdateManager.AVAILABLE
                                ? Ui.GREEN : Ui.MUTED);
                        if (result.status == UpdateManager.AVAILABLE && result.update != null) {
                            offerUpdate(result.update);
                        } else if (manual && result.status == UpdateManager.NO_UPDATE) {
                            Toast.makeText(MainActivity.this, result.message, Toast.LENGTH_SHORT).show();
                        }
                    }
                });
            }
        });
    }

    private void offerUpdate(final UpdateSecurity.ManifestData update) {
        String message = "版本 " + update.version;
        if (!update.notes.isEmpty()) message += "\n\n" + update.notes;
        new AlertDialog.Builder(this)
                .setTitle("发现安全更新")
                .setMessage(message)
                .setPositiveButton("更新", new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface dialog, int which) {
                        downloadUpdate(update);
                    }
                })
                .setNeutralButton("跳过此版本", new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface dialog, int which) {
                        UpdateManager.skip(MainActivity.this, update);
                        updateStatus.setText("已跳过版本 " + update.version);
                        updateStatus.setTextColor(Ui.MUTED);
                        Toast.makeText(MainActivity.this, "已跳过此版本", Toast.LENGTH_SHORT).show();
                    }
                })
                .setNegativeButton("稍后", null)
                .show();
    }

    private void downloadUpdate(final UpdateSecurity.ManifestData update) {
        updateButton.setEnabled(false);
        updateStatus.setText("正在下载并校验更新包");
        updateStatus.setTextColor(Ui.MUTED);
        UpdateManager.download(this, update, new UpdateManager.Callback() {
            @Override public void done(final UpdateManager.Result result) {
                runOnUiThread(new Runnable() {
                    @Override public void run() {
                        updateButton.setEnabled(true);
                        updateStatus.setText(result.message);
                        updateStatus.setTextColor(result.status == UpdateManager.READY
                                ? Ui.GREEN : Ui.RED);
                        if (result.status == UpdateManager.READY) continuePendingInstallation();
                    }
                });
            }
        });
    }

    private void offerPendingUpdate() {
        if (pendingUpdatePromptShown) return;
        pendingUpdatePromptShown = true;
        final String version = UpdateManager.pendingVersion(this);
        updateStatus.setText("版本 " + version + " 已下载并通过校验");
        updateStatus.setTextColor(Ui.GREEN);
        new AlertDialog.Builder(this)
                .setTitle("继续安装更新")
                .setMessage("更新包已安全下载。Android 系统仍会要求最后一次安装确认。")
                .setPositiveButton("继续", new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface dialog, int which) {
                        continuePendingInstallation();
                    }
                })
                .setNegativeButton("稍后", null)
                .show();
    }

    private void continuePendingInstallation() {
        updateStatus.setText("正在重新校验更新包");
        updateStatus.setTextColor(Ui.MUTED);
        UpdateManager.continueInstallation(this, new UpdateManager.Callback() {
            @Override public void done(final UpdateManager.Result result) {
                runOnUiThread(new Runnable() {
                    @Override public void run() {
                        updateStatus.setText(result.message);
                        updateStatus.setTextColor(result.status == UpdateManager.ERROR
                                ? Ui.RED : Ui.GREEN);
                        if (result.status == UpdateManager.PERMISSION_REQUIRED
                                || result.status == UpdateManager.INSTALLER_OPENED) {
                            pendingUpdatePromptShown = false;
                        }
                    }
                });
            }
        });
    }

    private boolean requestUpdateNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 904);
            return true;
        }
        return false;
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == 904) checkForUpdates(true);
    }

    private void refreshServerStatus() {
        ServerClient.check(this, new ServerClient.StatusCallback() {
            @Override public void done(final String status) {
                runOnUiThread(new Runnable() {
                    @Override public void run() {
                        if (ServerClient.ONLINE.equals(status)) {
                            credentialRecoveryRequired = false;
                            serverStatus.setText("服务器在线");
                            serverStatus.setTextColor(Ui.GREEN);
                            updateCredentialRecoveryVisibility();
                        } else if (ServerClient.OFFLINE.equals(status)) {
                            serverStatus.setText("无网络连接");
                            serverStatus.setTextColor(Ui.RED);
                            updateCredentialRecoveryVisibility();
                        } else if (ServerClient.AUTH_FAILED.equals(status)) {
                            credentialRecoveryRequired = true;
                            serverStatus.setText("设备凭据已失效 · 需要重新配对");
                            serverStatus.setTextColor(Ui.RED);
                            updateCredentialRecoveryVisibility();
                        } else {
                            serverStatus.setText("服务器不可用");
                            serverStatus.setTextColor(Ui.RED);
                            updateCredentialRecoveryVisibility();
                        }
                    }
                });
            }
        });
    }

    private void updateCredentialRecoveryVisibility() {
        recoverPairing.setVisibility(credentialRecoveryRequired && Prefs.paired(this)
                ? View.VISIBLE : View.GONE);
    }

    private LinearLayout settingRow(String labelValue) {
        LinearLayout row = Ui.row(this);
        row.setPadding(0, Ui.dp(this, 12), 0, 0);
        TextView label = Ui.title(this, labelValue, 14);
        label.setMinWidth(Ui.dp(this, 82));
        row.addView(label);
        return row;
    }

    private void addPrivacyOption(int id, String label, String tag, int left) {
        RadioButton button = new RadioButton(this);
        button.setId(id);
        button.setTag(tag);
        button.setText(label);
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
        boolean paired = Prefs.paired(this);
        connectionStatus.setText(paired ? "已连接" : "未连接");
        connectionStatus.setTextColor(paired ? Ui.GREEN : Ui.RED);
        connectionStatus.setBackground(Ui.background(
                this,
                paired ? Color.rgb(235, 247, 240) : Color.rgb(255, 241, 241),
                paired ? Color.rgb(183, 222, 200) : Color.rgb(241, 191, 191),
                99));
        receiverSummary.setText(paired ? "正在读取接收设备" : "尚未配对");
        appsSummary.setText(Prefs.filterAll(this)
                ? "全部应用"
                : Prefs.selectedPackages(this).size() + " 个应用");
        refreshListenerStatus();
        refreshReceiveStatus();
        if (paired) loadDestinations();
    }

    private void refreshReceiveStatus() {
        if (receiveStatus == null) return;
        if (!Prefs.localReceiverReady(this)) {
            receiveStatus.setText("尚未连接发送设备");
            receiveStatus.setTextColor(Ui.RED);
            return;
        }
        if (!Prefs.receiveEnabled(this)) {
            receiveStatus.setText("已配置 · 接收已关闭");
            receiveStatus.setTextColor(Ui.MUTED);
            return;
        }
        ReceiverBridgeService.start(this);
        String value = ReceiverBridgeService.status();
        receiveStatus.setText(value);
        receiveStatus.setTextColor("服务器在线".equals(value) ? Ui.GREEN : Ui.MUTED);
    }

    private void refreshListenerStatus() {
        boolean accessEnabled = ListenerBinding.isAccessEnabled(this);
        int health = ListenerHealth.state(
                accessEnabled,
                NotifyBridgeService.isRunning(),
                ListenerBinding.isConnected());
        if (health == ListenerHealth.READY || health == ListenerHealth.DISABLED) {
            listenerRepairAttempted = false;
            listenerRepairInProgress = false;
        }
        listenerSummary.setText(health == ListenerHealth.DISABLED
                ? "未允许"
                : health == ListenerHealth.READY
                ? "读取正常"
                : listenerRepairInProgress
                ? "正在请求系统重连"
                : listenerRepairAttempted
                ? "系统未恢复，请在设置中关闭再开启“转发”"
                : "权限已开启，等待系统连接");
        listenerSummary.setTextColor(health == ListenerHealth.READY
                ? Ui.GREEN
                : health == ListenerHealth.WAITING ? Ui.MUTED : Ui.RED);
        listenerButton.setText(health == ListenerHealth.DISABLED
                ? "设置"
                : health == ListenerHealth.READY
                ? "查看"
                : listenerRepairInProgress
                ? "重连中"
                : listenerRepairAttempted ? "去设置" : "重连");
        listenerButton.setEnabled(!listenerRepairInProgress);
    }

    private void refreshBackgroundStatus() {
        if (backgroundSummary == null || backgroundButton == null) return;
        boolean unrestricted = isIgnoringBatteryOptimizations();
        backgroundSummary.setText(unrestricted ? "电池限制已关闭" : "需要允许后台运行");
        backgroundSummary.setTextColor(unrestricted ? Ui.GREEN : Ui.RED);
        backgroundButton.setText(isVivoDevice() ? "自启动" : "设置");
    }

    private void loadDestinations() {
        PairingClient.destinations(this, new PairingClient.DestinationsCallback() {
            @Override
            public void done(final boolean ok, String message, final JSONArray destinations) {
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        if (!ok || destinations == null) {
                            receiverSummary.setText(Prefs.receiverName(MainActivity.this));
                            return;
                        }
                        List<String> names = new ArrayList<>();
                        List<String> platforms = new ArrayList<>();
                        for (int index = 0; index < destinations.length(); index++) {
                            JSONObject device = destinations.optJSONObject(index);
                            if (device == null) continue;
                            String name = device.optString("name", "接收设备").trim();
                            if (!name.isEmpty()) {
                                names.add(name);
                                String platform = device.optString("platform", "");
                                if ("macos".equals(platform)) {
                                    platforms.add(name.contains("Air") ? "Air" : "Mac");
                                } else if ("windows".equals(platform)) {
                                    platforms.add("Windows");
                                } else {
                                    platforms.add(name);
                                }
                            }
                        }
                        if (names.isEmpty()) {
                            receiverSummary.setText("尚未连接接收设备");
                        } else {
                            StringBuilder value = new StringBuilder();
                            List<String> displayNames = names.size() > 1 ? platforms : names;
                            for (String name : displayNames) {
                                if (value.length() > 0) value.append("、");
                                value.append(name);
                            }
                            value.append(" · ").append(names.size()).append(" 台");
                            receiverSummary.setText(value.toString());
                        }
                    }
                });
            }
        });
    }

    private void sendTest() {
        if (!Prefs.paired(this)) {
            testResult.setText("请先连接接收设备");
            testResult.setTextColor(Ui.RED);
            return;
        }
        try {
            JSONObject payload = new JSONObject();
            payload.put("id", "android-test-" + System.currentTimeMillis());
            payload.put("packageName", getPackageName());
            payload.put("appName", "转发测试");
            payload.put("title", "连接测试");
            payload.put("text", "手机与接收设备的通知链路正常");
            payload.put("postTime", System.currentTimeMillis());
            payload.put("privacyMode", Prefs.privacy(this));
            testResult.setText("正在发送");
            testResult.setTextColor(Ui.MUTED);
            BridgeSender.send(this, payload, new BridgeSender.Callback() {
                @Override
                public void done(final boolean ok, final String message) {
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            testResult.setText(ok ? "发送成功" : "发送失败 · " + message);
                            testResult.setTextColor(ok ? Ui.GREEN : Ui.RED);
                            if (ok) Toast.makeText(MainActivity.this, "发送成功", Toast.LENGTH_SHORT).show();
                            LogStore.add(MainActivity.this, (ok ? "测试成功 " : "测试失败 ") + message);
                        }
                    });
                }
            });
        } catch (Exception exception) {
            testResult.setText("发送失败 · " + exception.getMessage());
            testResult.setTextColor(Ui.RED);
        }
    }

    private boolean isIgnoringBatteryOptimizations() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return true;
        PowerManager manager = (PowerManager) getSystemService(POWER_SERVICE);
        return manager != null && manager.isIgnoringBatteryOptimizations(getPackageName());
    }

    private boolean isVivoDevice() {
        return Build.MANUFACTURER != null
                && Build.MANUFACTURER.toLowerCase().contains("vivo");
    }

    private void openBackgroundSettings() {
        if (isVivoDevice()) {
            try {
                Intent intent = new Intent("com.iqoo.secure.BGSTARTUPMANAGER");
                intent.setPackage("com.vivo.permissionmanager");
                startActivity(intent);
                Toast.makeText(this, "请确认“转发”允许自启动", Toast.LENGTH_SHORT).show();
                return;
            } catch (Exception ignored) {
            }
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                    && !isIgnoringBatteryOptimizations()) {
                Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
                intent.setData(Uri.parse("package:" + getPackageName()));
                startActivity(intent);
                return;
            }
        } catch (Exception ignored) {
        }
        try {
            startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
        } catch (Exception ignored) {
            startActivity(new Intent(
                    Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.parse("package:" + getPackageName())));
        }
    }
}
