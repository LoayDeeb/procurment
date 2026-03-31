import React, { useEffect, useRef, useState } from 'react';
import Markdown from 'react-markdown';
import Chatavatar from '../Assets/Chatavatar.png';
import UserAvatar from '../Assets/UserAvatar.png';
import { API_BASE } from '../config/api';
import { apiClient, formatApiError } from '../config/http';

const INITIAL_ASSISTANT_MESSAGE =
  'اهلا بك في مساعد المشتريات الخاص بشركة GIG الاردن. شاركني نطاق المشروع والمتطلبات الالزامية والجدول الزمني لابدا صياغة مسودة RFP دقيقة.';

const QUICK_PROMPTS = [
  'نحتاج منصة مطالبات رقمية مع تكامل مع انظمة التأمين الحالية.',
  'المشروع موجه لادارة الاكتتاب ونحتاج متطلبات الحوكمة والامتثال.',
  'نريد RFP لمركز خدمة عملاء رقمي متعدد القنوات خلال 6 اشهر.',
];

function isArabicText(text) {
  return /[\u0600-\u06FF]/.test(text || '');
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1 rounded-2xl bg-[#dfe9fb] px-3 py-2">
      <span className="chat-dot" />
      <span className="chat-dot chat-dot-delay-1" />
      <span className="chat-dot chat-dot-delay-2" />
    </div>
  );
}

export default function ChatPage({ user = { name: 'Procurement Officer', avatar: UserAvatar }, onBack }) {
  const [messages, setMessages] = useState([
    {
      from: 'Assistant',
      text: INITIAL_ASSISTANT_MESSAGE,
      isUser: false,
    },
  ]);
  const [input, setInput] = useState('');
  const [pdfUrl, setPdfUrl] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [apiHealthy, setApiHealthy] = useState(true);
  const [voiceInputSupported, setVoiceInputSupported] = useState(false);
  const [voiceOutputSupported, setVoiceOutputSupported] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [voiceOutputEnabled, setVoiceOutputEnabled] = useState(false);
  const [callModeEnabled, setCallModeEnabled] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [useElevenLabs, setUseElevenLabs] = useState(true);
  const chatContainerRef = useRef(null);
  const textareaRef = useRef(null);
  const resolvedUserAvatar = user?.avatar || UserAvatar;
  const isStreamingRef = useRef(false);
  const recognitionRef = useRef(null);
  const finalTranscriptRef = useRef('');
  const liveTranscriptRef = useRef('');
  const autoSendTimerRef = useRef(null);
  const lastAutoSentRef = useRef('');
  const queueAutoSendRef = useRef(() => {});
  const sendMessageRef = useRef(null);
  const audioRef = useRef(null);
  const callModeRef = useRef(false);
  const loadingRef = useRef(false);
  const speakingRef = useRef(false);

  const handleAvatarError = (e) => {
    if (e.currentTarget.dataset.fallbackApplied === 'true') return;
    e.currentTarget.dataset.fallbackApplied = 'true';
    e.currentTarget.src = UserAvatar;
  };

  useEffect(() => {
    callModeRef.current = callModeEnabled;
  }, [callModeEnabled]);

  useEffect(() => {
    loadingRef.current = loading;
  }, [loading]);

  useEffect(() => {
    speakingRef.current = isSpeaking;
  }, [isSpeaking]);

  const isNearBottom = () => {
    const container = chatContainerRef.current;
    if (!container) return true;
    return container.scrollHeight - container.scrollTop - container.clientHeight < 120;
  };

  const scrollToBottom = (behavior = 'smooth') => {
    const container = chatContainerRef.current;
    if (!container) return;
    container.scrollTo({ top: container.scrollHeight, behavior });
  };

  useEffect(() => {
    if (isStreamingRef.current) return;
    if (isNearBottom()) {
      scrollToBottom('smooth');
    }
  }, [messages, loading]);

  useEffect(() => {
    const checkHealth = async () => {
      try {
        await apiClient.get('/rfps');
        setApiHealthy(true);
      } catch {
        setApiHealthy(false);
      }
    };
    checkHealth();
  }, []);

  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    setVoiceInputSupported(Boolean(SpeechRecognition));
    setVoiceOutputSupported(Boolean(window.speechSynthesis && window.SpeechSynthesisUtterance));

    if (!SpeechRecognition) return;

    const recognition = new SpeechRecognition();
    recognition.lang = 'ar-JO';
    recognition.interimResults = true;
    recognition.continuous = true;

    recognition.onresult = (event) => {
      let interimTranscript = '';
      let finalTranscript = finalTranscriptRef.current;
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const piece = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalTranscript += `${piece} `;
        } else {
          interimTranscript += piece;
        }
      }
      finalTranscriptRef.current = finalTranscript.trim();
      const combined = `${finalTranscriptRef.current} ${interimTranscript}`.trim();
      liveTranscriptRef.current = combined;
      setInput(combined);
      queueAutoSendRef.current();
    };

    recognition.onerror = () => {
      setIsListening(false);
    };
    recognition.onend = () => {
      setIsListening(false);
      if (callModeRef.current && !loadingRef.current && !speakingRef.current) {
        try {
          recognition.start();
          setIsListening(true);
        } catch {
          setIsListening(false);
        }
      }
    };

    recognitionRef.current = recognition;
  }, []);

  const toggleListening = () => {
    if (!voiceInputSupported || !recognitionRef.current) return;
    if (isListening) {
      recognitionRef.current.stop();
      setIsListening(false);
      return;
    }
    try {
      recognitionRef.current.start();
      setIsListening(true);
    } catch {
      setIsListening(false);
    }
  };

  const speakWithElevenLabs = async (text) => {
    const res = await fetch(`${API_BASE}/tts/elevenlabs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) {
      throw new Error(`TTS service returned ${res.status}`);
    }
    const blob = await res.blob();
    const audioUrl = URL.createObjectURL(blob);
    const audio = new Audio(audioUrl);
    audioRef.current = audio;
    await new Promise((resolve, reject) => {
      audio.onended = resolve;
      audio.onerror = reject;
      audio.play().catch(reject);
    });
    URL.revokeObjectURL(audioUrl);
    audioRef.current = null;
  };

  const speakAssistantReply = async (text) => {
    if (!voiceOutputEnabled || !text?.trim()) return;
    setIsSpeaking(true);
    try {
      if (useElevenLabs) {
        await speakWithElevenLabs(text);
      } else if (voiceOutputSupported) {
        window.speechSynthesis.cancel();
        await new Promise((resolve) => {
          const utterance = new window.SpeechSynthesisUtterance(text);
          utterance.lang = isArabicText(text) ? 'ar-JO' : 'en-US';
          utterance.rate = 1;
          utterance.pitch = 1;
          utterance.onend = resolve;
          utterance.onerror = resolve;
          window.speechSynthesis.speak(utterance);
        });
      }
    } catch {
      if (voiceOutputSupported) {
        try {
          window.speechSynthesis.cancel();
          await new Promise((resolve) => {
            const utterance = new window.SpeechSynthesisUtterance(text);
            utterance.lang = isArabicText(text) ? 'ar-JO' : 'en-US';
            utterance.rate = 1;
            utterance.pitch = 1;
            utterance.onend = resolve;
            utterance.onerror = resolve;
            window.speechSynthesis.speak(utterance);
          });
        } catch {
          // no-op: speech is best-effort only
        }
      }
    } finally {
      setIsSpeaking(false);
    }
  };

  useEffect(() => {
    if (!textareaRef.current) return;
    textareaRef.current.style.height = '0px';
    textareaRef.current.style.height = `${Math.min(180, textareaRef.current.scrollHeight)}px`;
  }, [input]);

  const toOpenAIMessages = (msgs) =>
    msgs.map((msg) => ({
      role: msg.isUser ? 'user' : 'assistant',
      content: msg.text,
    }));

  const streamAssistantReply = async (fullText) => {
    const chunks = fullText.split(/(\s+)/).filter(Boolean);
    const assistantIndex = messages.length + 1;
    isStreamingRef.current = true;
    setMessages((prev) => [...prev, { from: 'Assistant', text: '', isUser: false }]);

    for (let i = 0; i < chunks.length; i += 1) {
      const nextText = chunks.slice(0, i + 1).join('');
      setMessages((prev) => {
        const draft = [...prev];
        if (draft[assistantIndex]) {
          draft[assistantIndex] = { ...draft[assistantIndex], text: nextText };
        }
        return draft;
      });

      if (i % 2 === 0) {
        scrollToBottom('auto');
      }
      await new Promise((resolve) => setTimeout(resolve, 18));
    }

    isStreamingRef.current = false;
    scrollToBottom('smooth');
    await speakAssistantReply(fullText);
  };

  const sendMessage = async (textOverride = null) => {
    const messageText = (textOverride ?? input).trim();
    if (!messageText || loading) return;

    const newMessages = [...messages, { from: user.name, text: messageText, isUser: true }];
    setMessages(newMessages);
    setInput('');
    finalTranscriptRef.current = '';
    liveTranscriptRef.current = '';
    setLoading(true);
    setError('');

    if (isListening && recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {
        // no-op
      }
      setIsListening(false);
    }

    try {
      const res = await fetch(`${API_BASE}/chat/rfp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: toOpenAIMessages(newMessages) }),
      });

      if (!res.ok) throw new Error(`Server returned ${res.status}`);

      const data = await res.json();
      if (data.pdf_url) setPdfUrl(data.pdf_url);
      await streamAssistantReply(data.reply || '');
      setApiHealthy(true);
    } catch (err) {
      const friendlyError = formatApiError(err, `Unable to connect to ${API_BASE}.`);
      setError(friendlyError);
      setApiHealthy(false);
      setMessages([
        ...newMessages,
        {
          from: 'Assistant',
          text: 'تعذر الوصول لخدمة التوليد حاليا. تاكد من تشغيل الخادم الخلفي ثم اعد المحاولة.',
          isUser: false,
        },
      ]);
    } finally {
      setLoading(false);
      if (callModeEnabled && voiceInputSupported && !isListening) {
        setTimeout(() => {
          if (!loading && !isSpeaking) {
            toggleListening();
          }
        }, 250);
      }
    }
  };
  sendMessageRef.current = sendMessage;

  const handleSubmit = async (e) => {
    e.preventDefault();
    await sendMessage();
  };

  const onComposerKeyDown = async (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      await sendMessage();
    }
  };

  const queueAutoSend = () => {
    if (!callModeRef.current) return;
    if (autoSendTimerRef.current) {
      clearTimeout(autoSendTimerRef.current);
    }
    autoSendTimerRef.current = setTimeout(() => {
      if (loadingRef.current || speakingRef.current) return;
      const text = liveTranscriptRef.current.trim();
      if (!text) return;
      if (text === lastAutoSentRef.current) return;
      lastAutoSentRef.current = text;
      if (sendMessageRef.current) {
        sendMessageRef.current(text);
      }
    }, 1300);
  };
  queueAutoSendRef.current = queueAutoSend;

  const toggleCallMode = () => {
    const next = !callModeEnabled;
    setCallModeEnabled(next);
    if (next) {
      setVoiceOutputEnabled(true);
      if (!isListening) {
        toggleListening();
      }
    } else {
      if (autoSendTimerRef.current) {
        clearTimeout(autoSendTimerRef.current);
        autoSendTimerRef.current = null;
      }
      finalTranscriptRef.current = '';
      liveTranscriptRef.current = '';
      lastAutoSentRef.current = '';
      if (isListening && recognitionRef.current) {
        recognitionRef.current.stop();
        setIsListening(false);
      }
      if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
    }
  };

  return (
    <div className="relative h-[calc(100vh-88px)] overflow-hidden bg-[#eef3ff] px-3 py-3 md:px-6 md:py-4">
      <div className="chat-bg-orb chat-bg-orb-a" />
      <div className="chat-bg-orb chat-bg-orb-b" />
      <div className="chat-bg-orb chat-bg-orb-c" />

      <div className="relative mx-auto grid h-full max-w-[1400px] gap-4 lg:grid-cols-[320px_1fr]">
        <aside className="rounded-2xl border border-[#d5def4] bg-white/85 p-4 shadow-[0_12px_28px_rgba(39,62,145,0.09)] backdrop-blur">
          <div className="mb-4 flex items-center gap-3">
            <img src={Chatavatar} alt="assistant avatar" className="h-11 w-11 rounded-xl object-cover" />
            <div>
              <h2 className="text-sm font-bold text-[#1f3280]">GIG Procurement Copilot</h2>
              <p className="text-xs text-[#60709c]">Jordan Insurance RFP Assistant</p>
            </div>
          </div>

          <div className="mb-4 rounded-xl border border-[#dce4f7] bg-[#f4f7ff] p-3">
            <p className="text-xs font-semibold text-[#273E91]">Connection Status</p>
            <p className={`mt-1 text-xs font-semibold ${apiHealthy ? 'text-[#0a8f66]' : 'text-[#c7372f]'}`}>
              {apiHealthy ? 'API Online' : 'API Offline'}
            </p>
          </div>

          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-[0.06em] text-[#60709c]">Quick Prompts</p>
            {QUICK_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => setInput(prompt)}
                className="w-full rounded-xl border border-[#d9e2f7] bg-white px-3 py-2 text-left text-xs text-[#33426f] transition hover:border-[#b4c6f2] hover:bg-[#f6f9ff]"
              >
                {prompt}
              </button>
            ))}
          </div>

          <div className="mt-4 space-y-2">
            <p className="text-xs font-semibold uppercase tracking-[0.06em] text-[#60709c]">Voice</p>
            <button
              type="button"
              disabled={!voiceInputSupported}
              onClick={toggleCallMode}
              className="w-full rounded-xl border border-[#c7d7fb] bg-[#eef4ff] px-3 py-2 text-left text-xs font-semibold text-[#22367f] transition hover:border-[#9cb7f2] hover:bg-[#e3edff] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {callModeEnabled ? 'End Call Mode' : 'Start Call Mode'}
            </button>
            <button
              type="button"
              disabled={!voiceInputSupported}
              onClick={toggleListening}
              className="w-full rounded-xl border border-[#d9e2f7] bg-white px-3 py-2 text-left text-xs font-semibold text-[#33426f] transition hover:border-[#b4c6f2] hover:bg-[#f6f9ff] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {voiceInputSupported
                ? isListening
                  ? 'Stop Dictation'
                  : 'Start Dictation'
                : 'Voice input not supported in this browser'}
            </button>
            <button
              type="button"
              onClick={() => setUseElevenLabs((prev) => !prev)}
              className="w-full rounded-xl border border-[#d9e2f7] bg-white px-3 py-2 text-left text-xs font-semibold text-[#33426f] transition hover:border-[#b4c6f2] hover:bg-[#f6f9ff]"
            >
              {useElevenLabs ? 'TTS Provider: ElevenLabs' : 'TTS Provider: Browser'}
            </button>
            <button
              type="button"
              disabled={!voiceOutputSupported && !useElevenLabs}
              onClick={() => setVoiceOutputEnabled((prev) => !prev)}
              className="w-full rounded-xl border border-[#d9e2f7] bg-white px-3 py-2 text-left text-xs font-semibold text-[#33426f] transition hover:border-[#b4c6f2] hover:bg-[#f6f9ff] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {(voiceOutputSupported || useElevenLabs)
                ? voiceOutputEnabled
                  ? 'Voice playback: ON'
                  : 'Voice playback: OFF'
                : 'Voice playback not supported in this browser'}
            </button>
          </div>

          {onBack ? (
            <button
              type="button"
              onClick={onBack}
              className="mt-4 w-full rounded-xl border border-[#c8d5f5] bg-white px-3 py-2 text-sm font-semibold text-[#273E91] hover:bg-[#f3f6ff]"
            >
              Back to Team
            </button>
          ) : null}
        </aside>

        <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-[#d5def4] bg-white/90 shadow-[0_16px_38px_rgba(39,62,145,0.14)] backdrop-blur">
          <header className="border-b border-[#e2e9f8] bg-white/80 px-5 py-4">
            <h3 className="text-lg font-bold text-[#22367f]">Live RFP Drafting Workspace</h3>
            <p className="text-xs text-[#60709c]">
              Conversation is tailored to GIG Insurance projects and can generate a structured draft PDF.
            </p>
          </header>

          {error ? (
            <div className="mx-5 mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>
          ) : null}

          <div className="flex-1 overflow-y-auto overscroll-contain px-4 py-4 md:px-6" ref={chatContainerRef}>
            <div className="space-y-4">
              {messages.map((msg, idx) => (
                <div key={idx} className={`chat-row ${msg.isUser ? 'chat-row-user' : 'chat-row-ai'}`}>
                  <img
                    src={msg.isUser ? resolvedUserAvatar : Chatavatar}
                    onError={handleAvatarError}
                    alt={msg.isUser ? 'user avatar' : 'assistant avatar'}
                    className="h-9 w-9 rounded-full border border-[#d9e2f7] object-cover"
                    loading="eager"
                    decoding="sync"
                  />
                  <div
                    dir={isArabicText(msg.text) ? 'rtl' : 'ltr'}
                    className={`chat-bubble ${
                      msg.isUser ? 'chat-bubble-user' : 'chat-bubble-ai'
                    } ${isArabicText(msg.text) ? 'chat-bubble-rtl' : 'chat-bubble-ltr'}`}
                  >
                    <Markdown>{msg.text}</Markdown>
                  </div>
                </div>
              ))}

              {loading ? (
                <div className="chat-row chat-row-ai">
                  <img src={Chatavatar} alt="assistant typing" className="h-9 w-9 rounded-full border border-[#d9e2f7] object-cover" />
                  <TypingIndicator />
                </div>
              ) : null}

              {pdfUrl ? (
                <div className="pt-1">
                  <a
                    href={`${API_BASE}${pdfUrl}`}
                    download
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex rounded-xl border border-[#b8c9f0] bg-[#f3f7ff] px-4 py-2 text-sm font-semibold text-[#22367f] hover:bg-[#e9f1ff]"
                  >
                    Download Draft RFP PDF
                  </a>
                </div>
              ) : null}
            </div>
          </div>

          <form className="border-t border-[#e2e9f8] bg-white px-4 py-4 md:px-6" onSubmit={handleSubmit}>
            <div className="flex gap-3">
              <textarea
                ref={textareaRef}
                rows={1}
                placeholder="Type scope, timeline, compliance rules, and expected deliverables..."
                className="max-h-[180px] min-h-[52px] flex-1 resize-none rounded-xl border border-[#c7d5f3] px-4 py-3 text-sm text-[#1f2c52] outline-none transition focus:border-[#6e89d8] focus:ring-2 focus:ring-[#d9e4ff]"
                dir={isArabicText(input) ? 'rtl' : 'ltr'}
                style={{ textAlign: isArabicText(input) ? 'right' : 'left' }}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onComposerKeyDown}
              />
              <button
                type="submit"
                disabled={!input.trim() || loading}
                className="rounded-xl bg-[#273E91] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#20357d] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? 'Working...' : 'Generate'}
              </button>
            </div>
            <p className="mt-2 text-[11px] text-[#6d7ca6]">Press Enter to send. Shift + Enter for new line.</p>
          </form>
        </section>
      </div>
    </div>
  );
}
