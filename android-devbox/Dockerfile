FROM ghcr.io/linuxserver/baseimage-selkies:debiantrixie

RUN mkdir -p /usr/share/man/man1 && apt-get update && apt-get install -y --no-install-recommends \
    openjdk-21-jre-headless unzip libpulse0 libnss3 libxcomposite1 \
    libxcursor1 libxi6 libxtst6 libxrandr2 libxdamage1 libxfixes3 \
    libasound2t64 libxss1 libx11-xcb1 libxinerama1 libxkbcommon-x11-0 \
    libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 \
    libxcb-xinerama0 libxcb-randr0 libxcb-render-util0 mousepad imv \
    && rm -rf /var/lib/apt/lists/*

ARG CMDLINE_TOOLS_VERSION=15859902
RUN curl -fsSL "https://dl.google.com/android/repository/commandlinetools-linux-${CMDLINE_TOOLS_VERSION}_latest.zip" -o /var/tmp/tools.zip \
    && unzip -q /var/tmp/tools.zip -d /opt/android-tools \
    && rm /var/tmp/tools.zip

COPY box-android /usr/local/bin/box-sdk
RUN chmod 755 /usr/local/bin/box-sdk && ln -s box-sdk /usr/local/bin/box-emulator

ENV ANDROID_HOME=/config/sdk \
    ANDROID_SDK_ROOT=/config/sdk \
    ANDROID_AVD_HOME=/config/.android/avd \
    ANDROID_EMULATOR_HOME=/config/.android \
    QT_QPA_PLATFORM=xcb \
    PATH=/config/sdk/cmdline-tools/latest/bin:/config/sdk/platform-tools:/config/sdk/emulator:/opt/android-tools/cmdline-tools/bin:${PATH}
