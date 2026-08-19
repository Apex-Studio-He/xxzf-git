package com.zundu.notifybridge;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.content.pm.ProviderInfo;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;

import java.io.File;
import java.io.FileNotFoundException;

public final class UpdateFileProvider extends ContentProvider {
    static final String AUTHORITY = "com.zundu.notifybridge.updates";
    static final String FILE_NAME = "forwarder-update.apk";

    @Override
    public void attachInfo(Context context, ProviderInfo info) {
        if (info.exported || !info.grantUriPermissions) {
            throw new SecurityException("update provider must remain private");
        }
        super.attachInfo(context, info);
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    static Uri contentUri() {
        return new Uri.Builder()
                .scheme("content")
                .authority(AUTHORITY)
                .appendPath(FILE_NAME)
                .build();
    }

    @Override
    public String getType(Uri uri) {
        requireTrustedUri(uri);
        return "application/vnd.android.package-archive";
    }

    @Override
    public Cursor query(
            Uri uri,
            String[] projection,
            String selection,
            String[] selectionArgs,
            String sortOrder) {
        requireTrustedUri(uri);
        File file = updateFile();
        String[] requested = projection == null
                ? new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE}
                : projection;
        java.util.ArrayList<String> columns = new java.util.ArrayList<>();
        java.util.ArrayList<Object> values = new java.util.ArrayList<>();
        for (String column : requested) {
            if (OpenableColumns.DISPLAY_NAME.equals(column)) {
                columns.add(column);
                values.add("转发-安全更新.apk");
            } else if (OpenableColumns.SIZE.equals(column)) {
                columns.add(column);
                values.add(file.length());
            }
        }
        MatrixCursor cursor = new MatrixCursor(columns.toArray(new String[0]), 1);
        cursor.addRow(values.toArray());
        return cursor;
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        requireTrustedUri(uri);
        if (!"r".equals(mode)) throw new FileNotFoundException("read-only update provider");
        if (getContext() == null
                || Prefs.get(getContext()).getString(Prefs.KEY_PENDING_UPDATE_MANIFEST, "").isEmpty()) {
            throw new FileNotFoundException("no verified update is pending");
        }
        File file = updateFile();
        try {
            String expected = new File(getContext().getFilesDir(), "updates/" + FILE_NAME)
                    .getCanonicalPath();
            if (!expected.equals(file.getCanonicalPath()) || !file.isFile()) {
                throw new FileNotFoundException("verified update unavailable");
            }
        } catch (FileNotFoundException error) {
            throw error;
        } catch (Exception error) {
            throw new FileNotFoundException("verified update unavailable");
        }
        return ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override public Uri insert(Uri uri, ContentValues values) {
        throw new UnsupportedOperationException("read-only");
    }

    @Override public int delete(Uri uri, String selection, String[] selectionArgs) {
        throw new UnsupportedOperationException("read-only");
    }

    @Override public int update(
            Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        throw new UnsupportedOperationException("read-only");
    }

    private void requireTrustedUri(Uri uri) {
        if (uri == null
                || !"content".equals(uri.getScheme())
                || !AUTHORITY.equals(uri.getAuthority())
                || uri.getPathSegments().size() != 1
                || !FILE_NAME.equals(uri.getPathSegments().get(0))
                || uri.getQuery() != null
                || uri.getFragment() != null) {
            throw new SecurityException("untrusted update URI");
        }
    }

    private File updateFile() {
        if (getContext() == null) return new File("/invalid");
        return new File(new File(getContext().getFilesDir(), "updates"), FILE_NAME);
    }
}
