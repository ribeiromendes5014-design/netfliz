from pathlib import Path

content = '''{% extends "base.html" %}

{% block title %}{{ video.title }} | Netfliz{% endblock %}

{% block content %}
<section class="panel video-player">
  <header>
    <h1>{{ video.title }}</h1>
    <p>{{ video.description }}</p>
    <a class="btn btn-secondary" href="{% url 'stream:tenant-portal' %}">
      Voltar ao catálogo</a>
  </header>
  <div
    class="player{% if video.rotate_180 %} rotated{% endif %}"
    data-rotate="{{ video.rotate_180|yesno:'1,0' }}"
  >
    <div class="video-viewport">
      <div class="video-rotate{% if video.rotate_180 %} enabled{% endif %}">
        <video
          {% if not video.rotate_180 %}controls{% endif %}
          poster="{{ video.cover_url }}"
          class="responsive{% if video.rotate_180 %} rotate-180{% endif %}"
          data-progress="{{ progress_position|default:0 }}"
          data-rotate="{{ video.rotate_180|yesno:'1,0' }}"
        >
          <source src="{{ video.source_url }}" type="{{ video.stream_mime }}" />
          Seu navegador não suporta este formato.
        </video>
      </div>
    </div>
    {% if video.rotate_180 %}
    <div class="custom-controls">
      <div class="control-actions">
        <button type="button" class="control-btn" data-action="toggle-play">
          Assistir
        </button>
        <button type="button" class="control-btn" data-action="fullscreen">
          Tela cheia
        </button>
      </div>
      <div class="progress-track">
        <input
          type="range"
          min="0"
          max="100"
          step="0.1"
          value="0"
          class="progress-slider"
        />
        <span class="time-display">00:00 / 00:00</span>
      </div>
    </div>
    {% endif %}
  </div>
</section>

<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
<script>
  document.addEventListener("DOMContentLoaded", () => {
    const videoElement = document.querySelector(".player video");
    const progressUrl = "{{ progress_url }}";
    const progressAttr = videoElement?.dataset.progress || "0";
    const initialPosition = parseFloat(
      progressAttr.toString().replace(",", ".")
    ) || 0;

    if (!progressUrl || !videoElement) {
      return;
    }

    const loadHlsSource = () => {
      const sourceUrl = "{{ video.source_url }}";
      const canPlayNative = videoElement.canPlayType("application/vnd.apple.mpegurl");
      if (canPlayNative) {
        videoElement.src = sourceUrl;
        return;
      }
      if (window.Hls && Hls.isSupported()) {
        const hls = new Hls();
        hls.loadSource(sourceUrl);
        hls.attachMedia(videoElement);
      } else {
        videoElement.src = sourceUrl;
      }
    };

    loadHlsSource();

    const getCookie = (name) => {
      const matches = document.cookie.match(new RegExp((?:^|; )=([^;]*)));
      return matches ? decodeURIComponent(matches[1]) : "";
    };

    const sendProgress = (position) => {
      fetch(progressUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCookie("csrftoken"),
        },
        body: JSON.stringify({ position }),
      }).catch(() => {});
    };

    const applyInitialPosition = () => {
      if (initialPosition <= 0) {
        return;
      }
      if (!isNaN(videoElement.duration) && videoElement.duration > 0) {
        videoElement.currentTime = Math.min(
          initialPosition,
          Math.max(0, videoElement.duration - 0.3)
        );
      } else {
        videoElement.currentTime = initialPosition;
      }
    };

    videoElement.addEventListener("loadedmetadata", applyInitialPosition);
    videoElement.addEventListener("durationchange", applyInitialPosition);
    if (videoElement.readyState > 0) {
      applyInitialPosition();
    }

    let updateTimer;
    const throttleUpdate = () => {
      if (updateTimer) {
        return;
      }
      updateTimer = setTimeout(() => {
        sendProgress(videoElement.currentTime);
        updateTimer = null;
      }, 4000);
    };

    videoElement.addEventListener("timeupdate", throttleUpdate);
    const persistPosition = () => sendProgress(videoElement.currentTime);
    videoElement.addEventListener("pause", persistPosition);
    videoElement.addEventListener("ended", persistPosition);
    window.addEventListener("beforeunload", persistPosition);

    const customControls = document.querySelector(".player.rotated .custom-controls");
    if (!customControls) {
      return;
    }

    const playButton = customControls.querySelector("[data-action='toggle-play']");
    const fullscreenButton = customControls.querySelector("[data-action='fullscreen']");
    const progressSlider = customControls.querySelector(".progress-slider");
    const timeDisplay = customControls.querySelector(".time-display");
    const playerWrapper = document.querySelector(".player.rotated");

    const formatTime = (value) => {
      if (isNaN(value) || value < 0) {
        return "00:00";
      }
      const minutes = Math.floor(value / 60);
      const seconds = Math.floor(value % 60);
      return ${minutes.toString().padStart(2, "0")}:;
    };

    const refreshTimeDisplay = () => {
      const current = videoElement.currentTime || 0;
      const duration = videoElement.duration || 0;
      timeDisplay.textContent = ${formatTime(current)} / ;
    };

    const refreshSlider = () => {
      if (!progressSlider || !videoElement.duration) {
        return;
      }
      const percent = (videoElement.currentTime / videoElement.duration) * 100;
      progressSlider.value = Math.min(100, Math.max(0, percent));
    };

    const updatePlayButton = () => {
      if (!playButton) {
        return;
      }
      playButton.textContent = videoElement.paused ? "Assistir" : "Pausar";
    };

    playButton?.addEventListener("click", () => {
      if (videoElement.paused) {
        videoElement.play();
      } else {
        videoElement.pause();
      }
    });

    progressSlider?.addEventListener("input", (event) => {
      if (!videoElement.duration) {
        return;
      }
      const percent = parseFloat(event.target.value) || 0;
      videoElement.currentTime = (percent / 100) * videoElement.duration;
      refreshTimeDisplay();
    });

    fullscreenButton?.addEventListener("click", () => {
      const request =
        playerWrapper.requestFullscreen ||
        playerWrapper.webkitRequestFullscreen ||
        playerWrapper.mozRequestFullScreen ||
        playerWrapper.msRequestFullscreen;
      if (request) {
        request.call(playerWrapper);
      }
    });

    videoElement.addEventListener("play", updatePlayButton);
    videoElement.addEventListener("pause", updatePlayButton);
    videoElement.addEventListener("timeupdate", () => {
      refreshSlider();
      refreshTimeDisplay();
    });
    videoElement.addEventListener("loadedmetadata", () => {
      refreshSlider();
      refreshTimeDisplay();
    });
    refreshSlider();
    refreshTimeDisplay();
    updatePlayButton();
  });
</script>
{% endblock %}
'''

Path('templates/stream/watch_video.html').write_text(content, encoding='utf-8')
