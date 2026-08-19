package com.zundu.notifybridge;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.CompoundButton;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import java.text.Collator;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

public class AppPickerActivity extends Activity {
    private final List<AppEntry> allApps = new ArrayList<>();
    private final List<AppEntry> visibleApps = new ArrayList<>();
    private final Set<String> selected = new HashSet<>();
    private AppAdapter adapter;
    private CheckBox allToggle;
    private TextView count;
    private ProgressBar loading;
    private String query = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Ui.SURFACE);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        selected.addAll(Prefs.selectedPackages(this));
        buildUi();
        loadApps();
    }

    @Override
    protected void onPause() {
        Prefs.savePackageSelection(this, allToggle.isChecked(), selected);
        super.onPause();
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
        Button back = Ui.button(this, "完成", false);
        bar.addView(back, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(this, 42)));
        TextView title = Ui.title(this, "选择转发应用", 19);
        LinearLayout.LayoutParams titleParams = new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
        titleParams.setMargins(Ui.dp(this, 12), 0, 0, 0);
        bar.addView(title, titleParams);
        count = Ui.subtitle(this, "读取中");
        bar.addView(count);
        root.addView(bar);

        LinearLayout controls = Ui.vertical(this);
        controls.setPadding(Ui.dp(this, 14), Ui.dp(this, 12), Ui.dp(this, 14), Ui.dp(this, 10));
        allToggle = new CheckBox(this);
        allToggle.setText("转发所有应用");
        allToggle.setTextColor(Ui.INK);
        allToggle.setTextSize(15);
        allToggle.setTypeface(Typeface.DEFAULT_BOLD);
        allToggle.setChecked(Prefs.filterAll(this));
        controls.addView(allToggle);

        EditText search = new EditText(this);
        search.setSingleLine(true);
        search.setHint("搜索 App 名称");
        search.setTextColor(Ui.INK);
        search.setHintTextColor(Ui.MUTED);
        search.setTextSize(14);
        search.setPadding(Ui.dp(this, 12), 0, Ui.dp(this, 12), 0);
        search.setBackground(Ui.background(this, Ui.SURFACE, Ui.LINE, 7));
        LinearLayout.LayoutParams searchParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 44));
        searchParams.setMargins(0, Ui.dp(this, 8), 0, 0);
        controls.addView(search, searchParams);
        root.addView(controls);

        loading = new ProgressBar(this);
        LinearLayout.LayoutParams loadingParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        loadingParams.setMargins(0, Ui.dp(this, 20), 0, Ui.dp(this, 20));
        root.addView(loading, loadingParams);

        ListView list = new ListView(this);
        list.setDividerHeight(0);
        list.setBackgroundColor(Ui.SURFACE);
        adapter = new AppAdapter();
        list.setAdapter(adapter);
        root.addView(list, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        setContentView(root);

        back.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                Prefs.savePackageSelection(AppPickerActivity.this, allToggle.isChecked(), selected);
                Toast.makeText(AppPickerActivity.this, "设置成功", Toast.LENGTH_SHORT).show();
                finish();
            }
        });
        allToggle.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            @Override
            public void onCheckedChanged(CompoundButton button, boolean checked) {
                adapter.notifyDataSetChanged();
                updateCount();
                Prefs.savePackageSelection(AppPickerActivity.this, checked, selected);
            }
        });
        search.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) {
                query = s.toString().trim().toLowerCase(Locale.ROOT);
                applyFilter();
            }
            @Override public void afterTextChanged(Editable editable) {}
        });
    }

    private void loadApps() {
        new Thread(new Runnable() {
            @Override
            public void run() {
                PackageManager manager = getPackageManager();
                List<AppEntry> loaded = new ArrayList<>();
                Set<String> seen = new HashSet<>();
                Intent launcher = new Intent(Intent.ACTION_MAIN);
                launcher.addCategory(Intent.CATEGORY_LAUNCHER);
                for (ResolveInfo resolved : manager.queryIntentActivities(launcher, 0)) {
                    ApplicationInfo info = resolved.activityInfo == null
                            ? null : resolved.activityInfo.applicationInfo;
                    if (info == null || !seen.add(info.packageName)) continue;
                    if (!info.enabled || getPackageName().equals(info.packageName)) continue;
                    CharSequence labelValue = resolved.loadLabel(manager);
                    String label = labelValue == null ? info.packageName : labelValue.toString();
                    Drawable icon;
                    try {
                        icon = resolved.loadIcon(manager);
                    } catch (Exception ignored) {
                        icon = manager.getDefaultActivityIcon();
                    }
                    loaded.add(new AppEntry(label, info.packageName, icon));
                }
                final Collator collator = Collator.getInstance(Locale.CHINA);
                Collections.sort(loaded, new Comparator<AppEntry>() {
                    @Override public int compare(AppEntry left, AppEntry right) {
                        return collator.compare(left.label, right.label);
                    }
                });
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        allApps.clear();
                        allApps.addAll(loaded);
                        loading.setVisibility(View.GONE);
                        applyFilter();
                    }
                });
            }
        }, "XXZF-AppList").start();
    }

    private void applyFilter() {
        visibleApps.clear();
        for (AppEntry entry : allApps) {
            if (query.isEmpty()
                    || entry.label.toLowerCase(Locale.ROOT).contains(query)
                    || entry.packageName.toLowerCase(Locale.ROOT).contains(query)) {
                visibleApps.add(entry);
            }
        }
        adapter.notifyDataSetChanged();
        updateCount();
    }

    private void updateCount() {
        count.setText(allToggle.isChecked() ? "全部" : selected.size() + " 个");
    }

    private void toggle(AppEntry entry) {
        if (allToggle.isChecked()) {
            allToggle.setChecked(false);
            selected.clear();
            selected.add(entry.packageName);
        } else if (!selected.add(entry.packageName)) {
            selected.remove(entry.packageName);
        }
        Prefs.savePackageSelection(this, allToggle.isChecked(), selected);
        adapter.notifyDataSetChanged();
        updateCount();
    }

    private final class AppAdapter extends BaseAdapter {
        @Override public int getCount() { return visibleApps.size(); }
        @Override public Object getItem(int position) { return visibleApps.get(position); }
        @Override public long getItemId(int position) { return position; }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            RowHolder holder;
            if (convertView == null) {
                LinearLayout row = Ui.row(AppPickerActivity.this);
                row.setPadding(Ui.dp(AppPickerActivity.this, 14), Ui.dp(AppPickerActivity.this, 9),
                        Ui.dp(AppPickerActivity.this, 14), Ui.dp(AppPickerActivity.this, 9));
                ImageView icon = new ImageView(AppPickerActivity.this);
                row.addView(icon, new LinearLayout.LayoutParams(
                        Ui.dp(AppPickerActivity.this, 42), Ui.dp(AppPickerActivity.this, 42)));
                LinearLayout text = Ui.vertical(AppPickerActivity.this);
                LinearLayout.LayoutParams textParams = new LinearLayout.LayoutParams(
                        0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
                textParams.setMargins(Ui.dp(AppPickerActivity.this, 12), 0, Ui.dp(AppPickerActivity.this, 8), 0);
                row.addView(text, textParams);
                TextView label = Ui.title(AppPickerActivity.this, "", 15);
                TextView packageName = Ui.subtitle(AppPickerActivity.this, "");
                packageName.setTextSize(11);
                text.addView(label);
                text.addView(packageName);
                CheckBox checked = new CheckBox(AppPickerActivity.this);
                checked.setClickable(false);
                row.addView(checked);
                holder = new RowHolder(icon, label, packageName, checked);
                row.setTag(holder);
                convertView = row;
            } else {
                holder = (RowHolder) convertView.getTag();
            }
            AppEntry entry = visibleApps.get(position);
            holder.icon.setImageDrawable(entry.icon);
            holder.label.setText(entry.label);
            holder.packageName.setText(entry.packageName);
            holder.checked.setChecked(allToggle.isChecked() || selected.contains(entry.packageName));
            convertView.setAlpha(allToggle.isChecked() ? 0.68f : 1f);
            convertView.setOnClickListener(new View.OnClickListener() {
                @Override public void onClick(View view) { toggle(entry); }
            });
            return convertView;
        }
    }

    private static final class AppEntry {
        final String label;
        final String packageName;
        final Drawable icon;

        AppEntry(String label, String packageName, Drawable icon) {
            this.label = label;
            this.packageName = packageName;
            this.icon = icon;
        }
    }

    private static final class RowHolder {
        final ImageView icon;
        final TextView label;
        final TextView packageName;
        final CheckBox checked;

        RowHolder(ImageView icon, TextView label, TextView packageName, CheckBox checked) {
            this.icon = icon;
            this.label = label;
            this.packageName = packageName;
            this.checked = checked;
        }
    }
}
