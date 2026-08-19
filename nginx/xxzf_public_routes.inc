    # Authoritative XXZF public/API routes. Managed only by the XXZF project.
    # Cross-origin browser requests are intentionally unsupported; the parent
    # HTTPS server rejects OPTIONS, while native clients use direct requests.

    location = /xxzf/notify {
        auth_basic off;
        access_log off;
        if ($request_method != POST) { return 405; }
        limit_req zone=zundu_api_per_ip burst=20 nodelay;
        client_max_body_size 256k;
        add_header Cache-Control "no-store, no-cache, must-revalidate" always;
        proxy_pass http://127.0.0.1:8787/api/notify;
        proxy_http_version 1.1;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 15s;
        proxy_send_timeout 15s;
        proxy_buffering off;
    }

    location = /xxzf/pair/start {
        auth_basic off;
        if ($request_method != POST) { return 405; }
        limit_req zone=zundu_api_per_ip burst=5 nodelay;
        client_max_body_size 16k;
        add_header Cache-Control "no-store" always;
        proxy_pass http://127.0.0.1:8787/api/pair/start;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 10s;
        proxy_send_timeout 10s;
        proxy_buffering off;
    }

    location = /xxzf/pair/claim {
        auth_basic off;
        if ($request_method != POST) { return 405; }
        limit_req zone=zundu_api_per_ip burst=10 nodelay;
        client_max_body_size 16k;
        add_header Cache-Control "no-store" always;
        proxy_pass http://127.0.0.1:8787/api/pair/claim;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 10s;
        proxy_send_timeout 10s;
        proxy_buffering off;
    }

    location = /xxzf/pair/status {
        auth_basic off;
        if ($request_method != GET) { return 405; }
        limit_req zone=zundu_api_per_ip burst=20 nodelay;
        add_header Cache-Control "no-store" always;
        proxy_pass http://127.0.0.1:8787/api/pair/status;
        proxy_http_version 1.1;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 10s;
        proxy_send_timeout 10s;
        proxy_buffering off;
    }

    location = /xxzf/v1/notify {
        auth_basic off;
        if ($request_method != POST) { return 405; }
        limit_req zone=zundu_api_per_ip burst=30 nodelay;
        client_max_body_size 64k;
        add_header Cache-Control "no-store" always;
        proxy_pass http://127.0.0.1:8787/api/v1/notify;
        proxy_http_version 1.1;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 15s;
        proxy_send_timeout 15s;
        proxy_buffering off;
    }

    location = /xxzf/v1/events {
        auth_basic off;
        if ($request_method != GET) { return 405; }
        limit_req zone=zundu_api_per_ip burst=10 nodelay;
        limit_conn zundu_conn_per_ip 4;
        add_header Cache-Control "no-store" always;
        proxy_pass http://127.0.0.1:8787/api/v1/events;
        proxy_http_version 1.1;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 1d;
        proxy_send_timeout 1d;
        proxy_buffering off;
        proxy_cache off;
    }

    location = /xxzf/v1/destinations {
        auth_basic off;
        if ($request_method != GET) { return 405; }
        limit_req zone=zundu_api_per_ip burst=20 nodelay;
        add_header Cache-Control "no-store" always;
        proxy_pass http://127.0.0.1:8787/api/v1/destinations;
        proxy_http_version 1.1;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 10s;
        proxy_send_timeout 10s;
        proxy_buffering off;
    }

    location = /xxzf/v1/bark/enroll/start {
        auth_basic off;
        if ($request_method != POST) { return 405; }
        limit_req zone=zundu_api_per_ip burst=5 nodelay;
        client_max_body_size 4k;
        add_header Cache-Control "no-store" always;
        proxy_pass http://127.0.0.1:8787/api/v1/bark/enroll/start;
        proxy_http_version 1.1;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 10s;
        proxy_send_timeout 10s;
        proxy_buffering off;
    }

    location = /xxzf/v1/bark/enroll/claim {
        auth_basic off;
        if ($request_method != POST) { return 405; }
        limit_req zone=zundu_api_per_ip burst=5 nodelay;
        client_max_body_size 8k;
        add_header Cache-Control "no-store" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
        proxy_pass http://127.0.0.1:8787/api/v1/bark/enroll/claim;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 15s;
        proxy_send_timeout 15s;
        proxy_buffering off;
    }

    location = /xxzf/v1/bark/test {
        auth_basic off;
        if ($request_method != POST) { return 405; }
        limit_req zone=zundu_api_per_ip burst=5 nodelay;
        client_max_body_size 4k;
        add_header Cache-Control "no-store" always;
        proxy_pass http://127.0.0.1:8787/api/v1/bark/test;
        proxy_http_version 1.1;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 15s;
        proxy_send_timeout 15s;
        proxy_buffering off;
    }

    location = /xxzf/v1/bark/revoke {
        auth_basic off;
        if ($request_method != POST) { return 405; }
        limit_req zone=zundu_api_per_ip burst=5 nodelay;
        client_max_body_size 4k;
        add_header Cache-Control "no-store" always;
        proxy_pass http://127.0.0.1:8787/api/v1/bark/revoke;
        proxy_http_version 1.1;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 10s;
        proxy_send_timeout 10s;
        proxy_buffering off;
    }

    location = /xxzf/bark {
        auth_basic off;
        access_log off;
        if ($request_method != GET) { return 405; }
        add_header Cache-Control "no-store" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
        return 302 /xxzf/bark/;
    }

    location = /xxzf/bark/ {
        auth_basic off;
        access_log off;
        if ($request_method != GET) { return 405; }
        alias /opt/xxzf/public/bark/;
        index index.html;
        default_type text/html;
        add_header Cache-Control "no-store, no-cache, must-revalidate" always;
        add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'" always;
        add_header Cross-Origin-Opener-Policy "same-origin" always;
        add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Frame-Options "DENY" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    location = /xxzf/bark/index.html {
        auth_basic off;
        access_log off;
        if ($request_method != GET) { return 405; }
        alias /opt/xxzf/public/bark/index.html;
        default_type text/html;
        add_header Cache-Control "no-store, no-cache, must-revalidate" always;
        add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'" always;
        add_header Cross-Origin-Opener-Policy "same-origin" always;
        add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Frame-Options "DENY" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    location = /xxzf/bark/bind.css {
        auth_basic off;
        access_log off;
        if ($request_method != GET) { return 405; }
        alias /opt/xxzf/public/bark/bind.css;
        default_type text/css;
        add_header Cache-Control "public, max-age=604800, immutable" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    location = /xxzf/bark/bind.js {
        auth_basic off;
        access_log off;
        if ($request_method != GET) { return 405; }
        alias /opt/xxzf/public/bark/bind.js;
        default_type application/javascript;
        add_header Cache-Control "public, max-age=604800, immutable" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    location = /xxzf/v1/device/revoke {
        auth_basic off;
        if ($request_method != POST) { return 405; }
        limit_req zone=zundu_api_per_ip burst=5 nodelay;
        client_max_body_size 4k;
        add_header Cache-Control "no-store" always;
        proxy_pass http://127.0.0.1:8787/api/v1/device/revoke;
        proxy_http_version 1.1;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 10s;
        proxy_send_timeout 10s;
        proxy_buffering off;
    }

    location = /xxzf/v1/receiver/senders/revoke {
        auth_basic off;
        access_log off;
        if ($request_method != POST) { return 405; }
        limit_req zone=zundu_api_per_ip burst=5 nodelay;
        client_max_body_size 4k;
        add_header Cache-Control "no-store" always;
        proxy_pass http://127.0.0.1:8787/api/v1/receiver/senders/revoke;
        proxy_http_version 1.1;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 10s;
        proxy_send_timeout 10s;
        proxy_buffering off;
    }

    location = /xxzf/v1/health {
        auth_basic off;
        if ($request_method != GET) { return 405; }
        limit_req zone=zundu_api_per_ip burst=20 nodelay;
        add_header Cache-Control "no-store" always;
        proxy_pass http://127.0.0.1:8787/api/v1/health;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 10s;
        proxy_send_timeout 10s;
        proxy_buffering off;
    }

    location = /xxzf/v1/device-status {
        auth_basic off;
        if ($request_method != GET) { return 405; }
        limit_req zone=zundu_api_per_ip burst=20 nodelay;
        add_header Cache-Control "no-store" always;
        proxy_pass http://127.0.0.1:8787/api/v1/device-status;
        proxy_http_version 1.1;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 10s;
        proxy_send_timeout 10s;
        proxy_buffering off;
    }

    location = /xxzf/v1/diagnostics {
        auth_basic off;
        if ($request_method != POST) { return 405; }
        limit_req zone=zundu_api_per_ip burst=5 nodelay;
        client_max_body_size 64k;
        add_header Cache-Control "no-store" always;
        proxy_pass http://127.0.0.1:8787/api/v1/diagnostics;
        proxy_http_version 1.1;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 15s;
        proxy_send_timeout 15s;
        proxy_buffering off;
    }

    location = /xxzf {
        auth_basic off;
        add_header Cache-Control "no-store" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
        return 404;
    }

    location ^~ /xxzf/ {
        auth_basic off;
        add_header Cache-Control "no-store" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
        return 404;
    }

    # Public test updates are produced by scripts/publish_test_update.py. The
    # clients independently verify the signed manifest, size, and SHA-256.
    location = /downloads/forwarder/test/android.json {
        auth_basic off;
        limit_except GET { deny all; }
        root /opt/xxzf/public;
        try_files $uri =404;
        default_type application/json;
        add_header Cache-Control "no-store, no-cache, must-revalidate" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    location = /downloads/forwarder/test/macos.json {
        auth_basic off;
        limit_except GET { deny all; }
        root /opt/xxzf/public;
        try_files $uri =404;
        default_type application/json;
        add_header Cache-Control "no-store, no-cache, must-revalidate" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    location = /downloads/forwarder/test/windows.json {
        auth_basic off;
        limit_except GET { deny all; }
        root /opt/xxzf/public;
        try_files $uri =404;
        default_type application/json;
        add_header Cache-Control "no-store, no-cache, must-revalidate" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    location = /downloads/forwarder/test/forwarder-android-0.9.3-test.apk {
        auth_basic off;
        limit_except GET { deny all; }
        root /opt/xxzf/public;
        try_files $uri =404;
        default_type application/vnd.android.package-archive;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    location = /downloads/forwarder/test/forwarder-android-0.9.4-test.apk {
        auth_basic off;
        limit_except GET { deny all; }
        root /opt/xxzf/public;
        try_files $uri =404;
        default_type application/vnd.android.package-archive;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    location = /downloads/forwarder/test/forwarder-android-0.9.6-test.apk {
        auth_basic off;
        limit_except GET { deny all; }
        root /opt/xxzf/public;
        try_files $uri =404;
        default_type application/vnd.android.package-archive;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    location = /downloads/forwarder/test/forwarder-android-0.9.7-test.apk {
        auth_basic off;
        limit_except GET { deny all; }
        root /opt/xxzf/public;
        try_files $uri =404;
        default_type application/vnd.android.package-archive;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    location = /downloads/forwarder/test/forwarder-android-0.9.11-test.apk {
        auth_basic off;
        limit_except GET { deny all; }
        root /opt/xxzf/public;
        try_files $uri =404;
        default_type application/vnd.android.package-archive;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    location = /downloads/forwarder/test/forwarder-android-0.9.16-test.apk {
        auth_basic off;
        limit_except GET { deny all; }
        root /opt/xxzf/public;
        try_files $uri =404;
        default_type application/vnd.android.package-archive;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    location = /downloads/forwarder/test/forwarder-macos-1.3.0-test.dmg {
        auth_basic off;
        limit_except GET { deny all; }
        root /opt/xxzf/public;
        try_files $uri =404;
        types { }
        default_type application/x-apple-diskimage;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    location = /downloads/forwarder/test/forwarder-macos-1.3.1-test.dmg {
        auth_basic off;
        limit_except GET { deny all; }
        root /opt/xxzf/public;
        try_files $uri =404;
        types { }
        default_type application/x-apple-diskimage;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    location = /downloads/forwarder/test/forwarder-macos-1.3.2-test.dmg {
        auth_basic off;
        limit_except GET { deny all; }
        root /opt/xxzf/public;
        try_files $uri =404;
        types { }
        default_type application/x-apple-diskimage;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    location = /downloads/forwarder/test/forwarder-windows-0.3.0-test.exe {
        auth_basic off;
        limit_except GET { deny all; }
        root /opt/xxzf/public;
        try_files $uri =404;
        types { }
        default_type application/vnd.microsoft.portable-executable;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    location = /downloads/forwarder/test/forwarder-windows-0.2.0-test.exe {
        auth_basic off;
        limit_except GET { deny all; }
        root /opt/xxzf/public;
        try_files $uri =404;
        types { }
        default_type application/vnd.microsoft.portable-executable;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

    # End public test update routes.

    location = /downloads/forwarder/forwarder-android-0.9.2.apk {
        auth_basic off;
        add_header Cache-Control "no-store" always;
        add_header X-Content-Type-Options "nosniff" always;
        return 410;
    }

    location = /downloads/forwarder/forwarder-macos-1.2.1.dmg {
        auth_basic off;
        add_header Cache-Control "no-store" always;
        add_header X-Content-Type-Options "nosniff" always;
        return 410;
    }

    location = /downloads/forwarder/forwarder-windows-0.2-setup.exe {
        auth_basic off;
        add_header Cache-Control "no-store" always;
        add_header X-Content-Type-Options "nosniff" always;
        return 410;
    }
