package com.zundu.notifybridge;

import android.content.Context;
import android.app.Activity;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

final class Ui {
    static final int BG = Color.rgb(246, 248, 250);
    static final int SURFACE = Color.WHITE;
    static final int INK = Color.rgb(26, 33, 43);
    static final int MUTED = Color.rgb(102, 114, 128);
    static final int LINE = Color.rgb(220, 225, 232);
    static final int BLUE = Color.rgb(9, 105, 218);
    static final int GREEN = Color.rgb(24, 121, 78);
    static final int RED = Color.rgb(190, 48, 48);

    private Ui() {}

    static int dp(Context context, int value) {
        return (int) (value * context.getResources().getDisplayMetrics().density + 0.5f);
    }

    static int statusBarInset(Activity activity) {
        int resource = activity.getResources().getIdentifier(
                "status_bar_height", "dimen", "android");
        if (resource > 0) return activity.getResources().getDimensionPixelSize(resource);
        return dp(activity, 28);
    }

    static GradientDrawable background(Context context, int color, int stroke, int radius) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(dp(context, radius));
        if (stroke != Color.TRANSPARENT) drawable.setStroke(dp(context, 1), stroke);
        return drawable;
    }

    static LinearLayout vertical(Context context) {
        LinearLayout layout = new LinearLayout(context);
        layout.setOrientation(LinearLayout.VERTICAL);
        return layout;
    }

    static LinearLayout row(Context context) {
        LinearLayout layout = new LinearLayout(context);
        layout.setOrientation(LinearLayout.HORIZONTAL);
        layout.setGravity(Gravity.CENTER_VERTICAL);
        return layout;
    }

    static LinearLayout section(Context context) {
        LinearLayout layout = vertical(context);
        layout.setPadding(dp(context, 16), dp(context, 14), dp(context, 16), dp(context, 14));
        layout.setBackground(background(context, SURFACE, LINE, 8));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.setMargins(0, 0, 0, dp(context, 10));
        layout.setLayoutParams(params);
        return layout;
    }

    static TextView title(Context context, String value, int size) {
        TextView view = new TextView(context);
        view.setText(value);
        view.setTextColor(INK);
        view.setTextSize(size);
        view.setTypeface(Typeface.DEFAULT_BOLD);
        return view;
    }

    static TextView subtitle(Context context, String value) {
        TextView view = new TextView(context);
        view.setText(value);
        view.setTextColor(MUTED);
        view.setTextSize(13);
        return view;
    }

    static TextView status(Context context, String value, boolean ok) {
        TextView view = new TextView(context);
        view.setText(value);
        view.setTextSize(12);
        view.setTextColor(ok ? GREEN : RED);
        view.setTypeface(Typeface.DEFAULT_BOLD);
        view.setGravity(Gravity.CENTER);
        view.setPadding(dp(context, 8), dp(context, 4), dp(context, 8), dp(context, 4));
        view.setBackground(background(
                context,
                ok ? Color.rgb(235, 247, 240) : Color.rgb(255, 241, 241),
                ok ? Color.rgb(183, 222, 200) : Color.rgb(241, 191, 191),
                99));
        return view;
    }

    static Button button(Context context, String value, boolean primary) {
        Button button = new Button(context);
        button.setAllCaps(false);
        button.setText(value);
        button.setTextSize(14);
        button.setTypeface(Typeface.DEFAULT_BOLD);
        button.setTextColor(primary ? Color.WHITE : BLUE);
        button.setMinHeight(dp(context, 44));
        button.setPadding(dp(context, 12), 0, dp(context, 12), 0);
        button.setBackground(background(
                context,
                primary ? BLUE : Color.rgb(238, 245, 253),
                primary ? BLUE : Color.rgb(190, 213, 240),
                7));
        return button;
    }

    static StateListDrawable segmentBackground(Context context) {
        StateListDrawable states = new StateListDrawable();
        states.addState(
                new int[]{android.R.attr.state_checked},
                background(context, BLUE, BLUE, 6));
        states.addState(
                new int[]{},
                background(context, SURFACE, LINE, 6));
        return states;
    }

    static ColorStateList segmentTextColors() {
        return new ColorStateList(
                new int[][]{
                        new int[]{android.R.attr.state_checked},
                        new int[]{}
                },
                new int[]{Color.WHITE, INK});
    }
}
