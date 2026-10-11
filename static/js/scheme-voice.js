(function () {
  'use strict';

  const supportedLanguages = {
    en: { name: 'English' },
    hi: { name: 'Hindi' },
    mr: { name: 'Marathi' },
    te: { name: 'Telugu' }
  };
  let activeAudio = null;
  let activeAudioUrl = null;
  let activeAudioCancel = null;
  let activeController = null;
  let requestId = 0;
  let activeNativeUtterance = null;
  let currentVolume = 0.9;

  function hasLanguageVoice(voices, languageCode) {
    return voices.some((voice) =>
      typeof voice.lang === 'string' &&
      voice.lang.toLowerCase().split('-')[0] === languageCode
    );
  }

  function getBrowserVoices(languageCode, timeoutMs = 5000) {
    const synthesis = window.speechSynthesis;
    if (!synthesis) return Promise.resolve([]);
    const currentVoices = synthesis.getVoices();
    if (hasLanguageVoice(currentVoices, languageCode)) {
      return Promise.resolve(currentVoices);
    }

    return new Promise((resolve) => {
      const timer = window.setTimeout(finish, timeoutMs);
      function finish() {
        synthesis.removeEventListener('voiceschanged', onVoicesChanged);
        resolve(synthesis.getVoices());
        window.clearTimeout(timer);
      }
      function onVoicesChanged() {
        if (hasLanguageVoice(synthesis.getVoices(), languageCode)) finish();
      }
      synthesis.addEventListener('voiceschanged', onVoicesChanged);
    });
  }

  function notify(callback, message) {
    if (typeof callback === 'function') callback(message);
  }

  function speakWithBrowserVoice(text, languageCode, voices, onStatus) {
    const language = supportedLanguages[languageCode];
    if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) {
      return Promise.reject(new Error('The browser does not support speech playback.'));
    }

    const voice = voices.find((item) =>
      item.lang.toLowerCase().startsWith(languageCode)
    );
    if (!voice) {
      return Promise.reject(new Error(
        `No ${language.name} voice is installed in this browser or on this device.`
      ));
    }

    return new Promise((resolve, reject) => {
      const utterance = new SpeechSynthesisUtterance(text);
      activeNativeUtterance = utterance;
      utterance.lang = voice.lang;
      utterance.voice = voice;
      utterance.volume = currentVolume;
      utterance.rate = 0.95;
      utterance.onstart = () => notify(
        onStatus,
        `Speaking translated scheme details in ${language.name}.`
      );
      utterance.onend = () => {
        activeNativeUtterance = null;
        resolve();
      };
      utterance.onerror = (event) => {
        activeNativeUtterance = null;
        reject(new Error(`Browser speech failed (${event.error || 'unknown error'}).`));
      };

      try {
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(utterance);
      } catch (error) {
        activeNativeUtterance = null;
        reject(new Error('The browser could not start speech playback.'));
      }
    });
  }

  function speechEndpoint(schemeId, languageCode) {
    const templateUrl = document.body.dataset.speechBaseUrl;
    if (!templateUrl) throw new Error('The scheme speech endpoint is not configured.');
    const path = templateUrl.replace(
      /\/0\/speech\/?$/,
      `/${encodeURIComponent(schemeId)}/speech/`
    );
    const endpoint = new URL(path, window.location.href);
    endpoint.searchParams.set('lang', languageCode);
    return endpoint;
  }

  function playAudio(blob, language, volume, onStatus, thisRequest) {
    return new Promise((resolve, reject) => {
      activeAudioUrl = URL.createObjectURL(blob);
      const audio = new Audio(activeAudioUrl);
      audio.volume = Math.min(1, Math.max(0, volume));
      activeAudio = audio;

      const cleanup = () => {
        audio.removeEventListener('ended', onEnded);
        audio.removeEventListener('error', onError);
        if (activeAudio === audio) activeAudio = null;
        if (activeAudioUrl) URL.revokeObjectURL(activeAudioUrl);
        activeAudioUrl = null;
        if (activeAudioCancel === cancel) activeAudioCancel = null;
      };
      const onEnded = () => {
        cleanup();
        resolve(true);
      };
      const onError = () => {
        cleanup();
        reject(new Error('The browser could not play the generated audio.'));
      };
      const cancel = () => {
        audio.pause();
        audio.removeAttribute('src');
        audio.load();
        cleanup();
        resolve(false);
      };

      activeAudioCancel = cancel;
      audio.addEventListener('ended', onEnded, { once: true });
      audio.addEventListener('error', onError, { once: true });
      audio.play().then(() => {
        if (thisRequest === requestId) {
          notify(onStatus, `Playing scheme information in ${language.name}.`);
        }
      }).catch(onError);
    });
  }

  async function speak(schemeId, languageValue, options = {}) {
    const languageCode = String(languageValue || '').toLowerCase();
    const language = supportedLanguages[languageCode];
    if (!language) throw new Error('Choose English, Hindi, Marathi, or Telugu.');
    if (!schemeId) throw new Error('The selected scheme could not be identified.');

    stop();
    const thisRequest = requestId;
    const controller = new AbortController();
    activeController = controller;
    const onStatus = options.onStatus;
    const volume = typeof options.volume === 'number' ? options.volume : currentVolume;
    currentVolume = Math.min(1, Math.max(0, volume));
    notify(
      onStatus,
      languageCode === 'en'
        ? 'Preparing English audio for this scheme...'
        : `Translating this scheme into ${language.name} and preparing audio...`
    );

    try {
      const response = await fetch(speechEndpoint(schemeId, languageCode), {
        signal: controller.signal,
        headers: { Accept: 'audio/mpeg, application/json' }
      });
      if (thisRequest !== requestId) return false;

      if (response.ok && response.headers.get('content-type')?.startsWith('audio/')) {
        const audio = await response.blob();
        if (!audio.size) throw new Error('The speech service returned empty audio.');
        return await playAudio(audio, language, currentVolume, onStatus, thisRequest);
      }

      let payload;
      try {
        payload = await response.json();
      } catch (error) {
        throw new Error(`The speech service returned an invalid response (HTTP ${response.status}).`);
      }

      if (payload.translated_text) {
        notify(onStatus, `Online speech is unavailable. Checking for a matching ${language.name} browser voice...`);
        const voices = await getBrowserVoices(languageCode);
        if (thisRequest !== requestId) return false;
        if (!voices.length) {
          throw new Error(
            `${payload.error || 'Online speech is unavailable.'} No browser speech voices are installed.`
          );
        }
        await speakWithBrowserVoice(
          payload.translated_text,
          languageCode,
          voices,
          onStatus
        );
        return true;
      }

      throw new Error(payload.error || `Speech request failed (HTTP ${response.status}).`);
    } catch (error) {
      if (error.name === 'AbortError' || thisRequest !== requestId) return false;
      throw error;
    } finally {
      if (activeController === controller) activeController = null;
    }
  }

  function stop() {
    requestId += 1;
    if (activeController) activeController.abort();
    activeController = null;
    if (activeAudioCancel) {
      activeAudioCancel();
    } else if (activeAudio) {
      activeAudio.pause();
      activeAudio.removeAttribute('src');
      activeAudio.load();
      activeAudio = null;
    }
    if (activeAudioUrl) URL.revokeObjectURL(activeAudioUrl);
    activeAudioUrl = null;
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    activeNativeUtterance = null;
  }

  function pause() {
    if (activeAudio) activeAudio.pause();
    else if (activeNativeUtterance && window.speechSynthesis) {
      window.speechSynthesis.pause();
    }
  }

  function resume() {
    if (activeAudio) return activeAudio.play();
    if (activeNativeUtterance && window.speechSynthesis) {
      window.speechSynthesis.resume();
    }
    return Promise.resolve();
  }

  function setVolume(volume) {
    currentVolume = Math.min(1, Math.max(0, volume));
    if (activeAudio) activeAudio.volume = currentVolume;
    if (activeNativeUtterance) activeNativeUtterance.volume = currentVolume;
  }

  window.SmartAssistVoice = {
    speak,
    stop,
    pause,
    resume,
    setVolume,
    getBrowserVoices
  };
})();
