package com.zundu.notifybridge;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.ImageFormat;
import android.graphics.Paint;
import android.graphics.SurfaceTexture;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.Image;
import android.media.ImageReader;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Size;
import android.view.Gravity;
import android.view.Surface;
import android.view.TextureView;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.TextView;

import com.google.zxing.BarcodeFormat;
import com.google.zxing.BinaryBitmap;
import com.google.zxing.DecodeHintType;
import com.google.zxing.MultiFormatReader;
import com.google.zxing.PlanarYUVLuminanceSource;
import com.google.zxing.Result;
import com.google.zxing.common.HybridBinarizer;

import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.EnumMap;
import java.util.Map;

public class QrScannerActivity extends Activity implements TextureView.SurfaceTextureListener {
    private static final int CAMERA_PERMISSION = 802;
    private TextureView preview;
    private HandlerThread cameraThread;
    private Handler cameraHandler;
    private CameraDevice camera;
    private CameraCaptureSession session;
    private ImageReader imageReader;
    private final MultiFormatReader decoder = new MultiFormatReader();
    private volatile boolean completed;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.BLACK);
        Map<DecodeHintType, Object> hints = new EnumMap<>(DecodeHintType.class);
        hints.put(DecodeHintType.POSSIBLE_FORMATS, Arrays.asList(BarcodeFormat.QR_CODE));
        hints.put(DecodeHintType.TRY_HARDER, Boolean.TRUE);
        decoder.setHints(hints);
        buildUi();
    }

    private void buildUi() {
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        preview = new TextureView(this);
        preview.setSurfaceTextureListener(this);
        root.addView(preview, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        root.addView(new ScanOverlay(this), new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        Button close = Ui.button(this, "返回", false);
        FrameLayout.LayoutParams closeParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(this, 44), Gravity.TOP | Gravity.START);
        closeParams.setMargins(
                Ui.dp(this, 14),
                Ui.statusBarInset(this) + Ui.dp(this, 14),
                0,
                0);
        root.addView(close, closeParams);

        TextView hint = new TextView(this);
        hint.setText("扫描电脑上的讯桥二维码");
        hint.setTextColor(Color.WHITE);
        hint.setTextSize(15);
        hint.setGravity(Gravity.CENTER);
        FrameLayout.LayoutParams hintParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 48), Gravity.BOTTOM);
        hintParams.setMargins(Ui.dp(this, 20), 0, Ui.dp(this, 20), Ui.dp(this, 38));
        root.addView(hint, hintParams);
        setContentView(root);
        close.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { finish(); }
        });
    }

    @Override
    protected void onResume() {
        super.onResume();
        cameraThread = new HandlerThread("XXZF-QR-Camera");
        cameraThread.start();
        cameraHandler = new Handler(cameraThread.getLooper());
        if (preview.isAvailable()) openCamera();
    }

    @Override
    protected void onPause() {
        closeCamera();
        if (cameraThread != null) {
            cameraThread.quitSafely();
            cameraThread = null;
            cameraHandler = null;
        }
        super.onPause();
    }

    private void openCamera() {
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, CAMERA_PERMISSION);
            return;
        }
        try {
            CameraManager manager = (CameraManager) getSystemService(CAMERA_SERVICE);
            String chosen = null;
            Size scanSize = new Size(1280, 720);
            for (String id : manager.getCameraIdList()) {
                CameraCharacteristics characteristics = manager.getCameraCharacteristics(id);
                Integer facing = characteristics.get(CameraCharacteristics.LENS_FACING);
                if (facing == null || facing != CameraCharacteristics.LENS_FACING_BACK) continue;
                chosen = id;
                StreamConfigurationMap map = characteristics.get(
                        CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
                if (map != null) scanSize = chooseSize(map.getOutputSizes(ImageFormat.YUV_420_888));
                break;
            }
            if (chosen == null) throw new CameraAccessException(CameraAccessException.CAMERA_ERROR);
            imageReader = ImageReader.newInstance(
                    scanSize.getWidth(), scanSize.getHeight(), ImageFormat.YUV_420_888, 2);
            imageReader.setOnImageAvailableListener(new ImageReader.OnImageAvailableListener() {
                @Override
                public void onImageAvailable(ImageReader reader) {
                    decodeImage(reader);
                }
            }, cameraHandler);
            manager.openCamera(chosen, cameraCallback, cameraHandler);
        } catch (Exception exception) {
            finishWithError();
        }
    }

    private Size chooseSize(Size[] sizes) {
        if (sizes == null || sizes.length == 0) return new Size(1280, 720);
        Size best = sizes[0];
        long bestDelta = Long.MAX_VALUE;
        for (Size size : sizes) {
            long pixels = (long) size.getWidth() * size.getHeight();
            long delta = Math.abs(pixels - 1280L * 720L);
            if (pixels >= 640L * 480L && delta < bestDelta) {
                best = size;
                bestDelta = delta;
            }
        }
        return best;
    }

    private final CameraDevice.StateCallback cameraCallback = new CameraDevice.StateCallback() {
        @Override
        public void onOpened(CameraDevice device) {
            camera = device;
            createSession();
        }

        @Override public void onDisconnected(CameraDevice device) { device.close(); camera = null; }
        @Override public void onError(CameraDevice device, int error) { device.close(); camera = null; finishWithError(); }
    };

    private void createSession() {
        try {
            SurfaceTexture texture = preview.getSurfaceTexture();
            if (texture == null || camera == null || imageReader == null) return;
            texture.setDefaultBufferSize(imageReader.getWidth(), imageReader.getHeight());
            Surface previewSurface = new Surface(texture);
            CaptureRequest.Builder request = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
            request.addTarget(previewSurface);
            request.addTarget(imageReader.getSurface());
            camera.createCaptureSession(
                    Arrays.asList(previewSurface, imageReader.getSurface()),
                    new CameraCaptureSession.StateCallback() {
                        @Override
                        public void onConfigured(CameraCaptureSession value) {
                            session = value;
                            try {
                                request.set(CaptureRequest.CONTROL_AF_MODE,
                                        CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE);
                                session.setRepeatingRequest(request.build(), null, cameraHandler);
                            } catch (CameraAccessException ignored) {
                                finishWithError();
                            }
                        }

                        @Override public void onConfigureFailed(CameraCaptureSession value) { finishWithError(); }
                    },
                    cameraHandler);
        } catch (Exception exception) {
            finishWithError();
        }
    }

    private void decodeImage(ImageReader reader) {
        Image image = reader.acquireLatestImage();
        if (image == null) return;
        try {
            if (completed) return;
            Image.Plane plane = image.getPlanes()[0];
            ByteBuffer buffer = plane.getBuffer();
            int width = image.getWidth();
            int height = image.getHeight();
            int rowStride = plane.getRowStride();
            int pixelStride = plane.getPixelStride();
            byte[] luminance = new byte[width * height];
            byte[] row = new byte[rowStride];
            for (int y = 0; y < height; y++) {
                int length = Math.min(rowStride, buffer.remaining());
                buffer.get(row, 0, length);
                for (int x = 0; x < width; x++) {
                    int source = x * pixelStride;
                    luminance[y * width + x] = source < length ? row[source] : 0;
                }
            }
            PlanarYUVLuminanceSource source = new PlanarYUVLuminanceSource(
                    luminance, width, height, 0, 0, width, height, false);
            Result result = decoder.decodeWithState(new BinaryBitmap(new HybridBinarizer(source)));
            if (result != null && result.getText() != null) finishWithPayload(result.getText());
        } catch (Exception ignored) {
            decoder.reset();
        } finally {
            image.close();
        }
    }

    private void finishWithPayload(String payload) {
        if (completed) return;
        completed = true;
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                Intent data = new Intent();
                data.putExtra("payload", payload);
                setResult(RESULT_OK, data);
                finish();
            }
        });
    }

    private void finishWithError() {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                setResult(RESULT_CANCELED);
                finish();
            }
        });
    }

    private void closeCamera() {
        if (session != null) { session.close(); session = null; }
        if (camera != null) { camera.close(); camera = null; }
        if (imageReader != null) { imageReader.close(); imageReader = null; }
    }

    @Override public void onSurfaceTextureAvailable(SurfaceTexture surface, int width, int height) { openCamera(); }
    @Override public void onSurfaceTextureSizeChanged(SurfaceTexture surface, int width, int height) {}
    @Override public boolean onSurfaceTextureDestroyed(SurfaceTexture surface) { return true; }
    @Override public void onSurfaceTextureUpdated(SurfaceTexture surface) {}

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode == CAMERA_PERMISSION && results.length > 0
                && results[0] == PackageManager.PERMISSION_GRANTED) {
            openCamera();
        } else {
            finishWithError();
        }
    }

    private static final class ScanOverlay extends View {
        private final Paint shade = new Paint();
        private final Paint frame = new Paint();

        ScanOverlay(Activity context) {
            super(context);
            shade.setColor(Color.argb(125, 0, 0, 0));
            frame.setColor(Color.WHITE);
            frame.setStyle(Paint.Style.STROKE);
            frame.setStrokeWidth(Ui.dp(context, 3));
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float size = Math.min(getWidth() * 0.72f, getHeight() * 0.42f);
            float left = (getWidth() - size) / 2f;
            float top = (getHeight() - size) / 2f;
            float right = left + size;
            float bottom = top + size;
            canvas.drawRect(0, 0, getWidth(), top, shade);
            canvas.drawRect(0, bottom, getWidth(), getHeight(), shade);
            canvas.drawRect(0, top, left, bottom, shade);
            canvas.drawRect(right, top, getWidth(), bottom, shade);
            canvas.drawRoundRect(left, top, right, bottom, Ui.dp(getContext(), 8), Ui.dp(getContext(), 8), frame);
        }
    }
}
