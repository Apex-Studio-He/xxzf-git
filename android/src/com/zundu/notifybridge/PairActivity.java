package com.zundu.notifybridge;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputFilter;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

public class PairActivity extends Activity {
    private static final int REQUEST_SCAN = 700;
    private EditText code;
    private Button pair;
    private TextView result;
    private String serverBase;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Ui.SURFACE);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        serverBase = Prefs.serverBase(this);
        buildUi();
    }

    private void buildUi() {
        LinearLayout root = Ui.vertical(this);
        root.setBackgroundColor(Ui.BG);

        LinearLayout bar = Ui.row(this);
        bar.setPadding(
                Ui.dp(this, 10),
                Ui.statusBarInset(this) + Ui.dp(this, 10),
                Ui.dp(this, 14),
                Ui.dp(this, 10));
        bar.setBackgroundColor(Ui.SURFACE);
        Button back = Ui.button(this, "返回", false);
        bar.addView(back, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(this, 42)));
        TextView heading = Ui.title(this, "管理接收设备", 19);
        LinearLayout.LayoutParams headingParams = new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
        headingParams.setMargins(Ui.dp(this, 12), 0, 0, 0);
        bar.addView(heading, headingParams);
        root.addView(bar);

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout content = Ui.vertical(this);
        content.setPadding(Ui.dp(this, 14), Ui.dp(this, 16), Ui.dp(this, 14), Ui.dp(this, 20));
        scroll.addView(content, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(scroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));

        if (Prefs.paired(this)) {
            LinearLayout current = Ui.section(this);
            current.addView(Ui.title(this, "当前发送身份", 17));
            TextView receiver = Ui.subtitle(this, Prefs.receiverName(this));
            receiver.setPadding(0, Ui.dp(this, 5), 0, 0);
            current.addView(receiver);
            TextView fingerprint = Ui.subtitle(
                    this, "设备编号 " + Prefs.receiverFingerprint(this));
            fingerprint.setPadding(0, Ui.dp(this, 3), 0, 0);
            current.addView(fingerprint);
            Button manageIphone = Ui.button(this, "管理 iPhone（Bark）", true);
            LinearLayout.LayoutParams manageIphoneParams = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 44));
            manageIphoneParams.setMargins(0, Ui.dp(this, 14), 0, 0);
            current.addView(manageIphone, manageIphoneParams);
            Button disconnect = Ui.button(this, "解除全部连接", false);
            LinearLayout.LayoutParams disconnectParams = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 44));
            disconnectParams.setMargins(0, Ui.dp(this, 8), 0, 0);
            current.addView(disconnect, disconnectParams);
            Button recover = Ui.button(this, "凭据失效？重新配对", false);
            LinearLayout.LayoutParams recoverParams = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 44));
            recoverParams.setMargins(0, Ui.dp(this, 8), 0, 0);
            current.addView(recover, recoverParams);
            content.addView(current);
            disconnect.setOnClickListener(new View.OnClickListener() {
                @Override public void onClick(View view) { confirmDisconnect(); }
            });
            manageIphone.setOnClickListener(new View.OnClickListener() {
                @Override public void onClick(View view) {
                    startActivity(new Intent(PairActivity.this, BarkDestinationActivity.class));
                }
            });
            recover.setOnClickListener(new View.OnClickListener() {
                @Override public void onClick(View view) {
                    CredentialRecovery.confirmAndClear(PairActivity.this, new Runnable() {
                        @Override public void run() {
                            Toast.makeText(PairActivity.this,
                                    "本机失效凭据已清除，请重新配对",
                                    Toast.LENGTH_SHORT).show();
                            recreate();
                        }
                    });
                }
            });
        }

        LinearLayout pairing = Ui.section(this);
        pairing.addView(Ui.title(this, "连接接收设备", 17));
        TextView hint = Ui.subtitle(this, "输入接收设备显示的 6 位配对码，有效期 5 分钟");
        hint.setPadding(0, Ui.dp(this, 3), 0, Ui.dp(this, 12));
        pairing.addView(hint);

        code = new EditText(this);
        code.setSingleLine(true);
        code.setGravity(Gravity.CENTER);
        code.setTextSize(28);
        code.setTextColor(Ui.INK);
        code.setHintTextColor(Ui.MUTED);
        code.setHint("000000");
        code.setInputType(InputType.TYPE_CLASS_NUMBER);
        code.setFilters(new InputFilter[]{new InputFilter.LengthFilter(6)});
        code.setBackground(Ui.background(this, Ui.SURFACE, Ui.LINE, 7));
        pairing.addView(code, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 58)));

        LinearLayout actions = Ui.row(this);
        LinearLayout.LayoutParams actionsParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        actionsParams.setMargins(0, Ui.dp(this, 10), 0, 0);
        pairing.addView(actions, actionsParams);
        Button scan = Ui.button(this, "扫描二维码", false);
        pair = Ui.button(this, "连接", true);
        actions.addView(scan, weighted(1, 0, 46));
        actions.addView(pair, weighted(1, Ui.dp(this, 8), 46));

        result = Ui.subtitle(this, "");
        result.setPadding(0, Ui.dp(this, 10), 0, 0);
        pairing.addView(result);
        content.addView(pairing);

        setContentView(root);

        back.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { finish(); }
        });
        scan.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                startActivityForResult(
                        new Intent(PairActivity.this, QrScannerActivity.class), REQUEST_SCAN);
            }
        });
        pair.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { submit(); }
        });
    }

    private LinearLayout.LayoutParams weighted(int weight, int left, int height) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                0, Ui.dp(this, height), weight);
        params.setMargins(left, 0, 0, 0);
        return params;
    }

    private void submit() {
        String value = code.getText().toString().trim();
        if (value.length() != 6) {
            setPairResult("请输入 6 位配对码", false);
            return;
        }
        pair.setEnabled(false);
        setPairResult("正在连接", true);
        PairingClient.claim(this, serverBase, value, new PairingClient.Callback() {
            @Override
            public void done(final boolean ok, final String message, JSONObject device) {
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        pair.setEnabled(true);
                        setPairResult(message, ok);
                        if (ok) {
                            Toast.makeText(PairActivity.this, "连接成功", Toast.LENGTH_SHORT).show();
                            setResult(RESULT_OK);
                            recreate();
                        }
                    }
                });
            }
        });
    }

    private void setPairResult(String value, boolean ok) {
        result.setText(value);
        result.setTextColor(ok ? Ui.GREEN : Ui.RED);
    }

    private void confirmDisconnect() {
        new AlertDialog.Builder(this)
                .setTitle("解除全部连接？")
                .setMessage("这台手机将停止向所有已连接的电脑和手机转发通知。")
                .setNegativeButton("取消", null)
                .setPositiveButton("解除", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        setPairResult("正在安全解除连接…", true);
                        PairingClient.selfRevoke(
                                PairActivity.this,
                                new PairingClient.ActionCallback() {
                                    @Override
                                    public void done(final boolean ok, final String message) {
                                        runOnUiThread(new Runnable() {
                                            @Override
                                            public void run() {
                                                if (!ok) {
                                                    setPairResult(
                                                            message == null
                                                                    ? "解除失败，本地凭据已保留"
                                                                    : message,
                                                            false);
                                                    return;
                                                }
                                                Prefs.clearPairing(PairActivity.this);
                                                Toast.makeText(
                                                        PairActivity.this,
                                                        "已解除全部连接",
                                                        Toast.LENGTH_SHORT).show();
                                                recreate();
                                            }
                                        });
                                    }
                                });
                    }
                })
                .show();
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_SCAN || resultCode != RESULT_OK || data == null) return;
        String payload = data.getStringExtra("payload");
        try {
            Uri uri = Uri.parse(payload);
            if (!"xxzf".equals(uri.getScheme()) || !"pair".equals(uri.getHost())) {
                throw new IllegalArgumentException();
            }
            String scannedServer = ServerPolicy.requireOfficialBase(
                    uri.getQueryParameter("server"));
            String scannedCode = uri.getQueryParameter("code");
            if (scannedServer == null || scannedCode == null || scannedCode.length() != 6) {
                throw new IllegalArgumentException();
            }
            serverBase = scannedServer;
            code.setText(scannedCode);
            submit();
        } catch (Exception ignored) {
            setPairResult("这不是转发配对码", false);
        }
    }

}
