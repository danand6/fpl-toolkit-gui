import { useEffect, useState } from 'react';
import LoginForm from './components/LoginForm.jsx';
import ChatInterface from './components/ChatInterface.jsx';
import FeatureContent from './components/FeatureContent.jsx';
import StatusBar from './components/StatusBar.jsx';
import { FEATURE_PROMPTS } from './constants/features.js';
import { fetchFeature, getSession, login, logout, sendChatMessage } from './api/client.js';

const HOME_RESULT = {
  type: 'text',
  data: 'Welcome to the FPL Toolkit!\n\nAsk me about your team, captains, transfers, or injuries.'
};

const INITIAL_STATUS = 'Checking saved session…';

export default function App() {
  const [session, setSession] = useState({ loading: true, data: null, error: null });
  const [statusMessage, setStatusMessage] = useState(INITIAL_STATUS);
  const [loginError, setLoginError] = useState('');
  const [loginPending, setLoginPending] = useState(false);
  const [featureResult, setFeatureResult] = useState(HOME_RESULT);
  const [featureLoading, setFeatureLoading] = useState(false);
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Hi! Ask me anything about your FPL squad or pick a suggestion below.' }
  ]);
  const [chatPrompts, setChatPrompts] = useState(FEATURE_PROMPTS);

  const isLoggedIn = Boolean(session.data?.logged_in);
  const userName = session.data?.user_name;

  useEffect(() => {
    let isMounted = true;

    async function hydrateSession() {
      setStatusMessage(INITIAL_STATUS);
      try {
        const data = await getSession();
        if (!isMounted) return;
        setSession({ loading: false, data, error: null });
        if (data.logged_in) {
          setFeatureResult(HOME_RESULT);
          setStatusMessage('Ready.');
        } else {
          setStatusMessage('Please log in to continue.');
        }
      } catch (error) {
        if (!isMounted) return;
        setSession({ loading: false, data: null, error: error.message });
        setStatusMessage('Unable to load session info.');
      }
    }

    hydrateSession();

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    if (!isLoggedIn) {
      setFeatureResult(HOME_RESULT);
      setMessages([
        { role: 'assistant', content: 'You are logged out. Log in again to continue.' }
      ]);
      setChatPrompts(FEATURE_PROMPTS);
    }
  }, [isLoggedIn]);

  const handleLogin = async (teamId, leagueId) => {
    setLoginPending(true);
    setLoginError('');
    setStatusMessage('Verifying details…');
    try {
      const data = await login(teamId, leagueId);
      setSession({ loading: false, data: { ...data, logged_in: true }, error: null });
      setFeatureResult(HOME_RESULT);
      setMessages([
        { role: 'assistant', content: `Welcome back, ${data.user_name}! Ask me about your team anytime.` }
      ]);
      setChatPrompts(FEATURE_PROMPTS);
      setStatusMessage(`Welcome, ${data.user_name}! Ask me about your team.`);
    } catch (error) {
      setLoginError(error.message);
      setStatusMessage('Login failed.');
    } finally {
      setLoginPending(false);
    }
  };

  const handleLogout = async () => {
    setStatusMessage('Logging out…');
    try {
      await logout();
    } catch (error) {
      // Still reset local state even if the server call fails.
      console.error('Logout error:', error);
    } finally {
      setSession({ loading: false, data: { logged_in: false }, error: null });
      setFeatureResult(HOME_RESULT);
      setMessages([
        { role: 'assistant', content: 'You are logged out. Log in again to continue.' }
      ]);
      setChatPrompts(FEATURE_PROMPTS);
      setStatusMessage('Logged out.');
    }
  };

  const handleChatMessage = async (input) => {
    if (!input) return;

    setMessages((msgs) => [...msgs, { role: 'user', content: input }]);

    if (!isLoggedIn) {
      setMessages((msgs) => [
        ...msgs,
        { role: 'assistant', content: 'Please log in first so I can access your team data.' }
      ]);
      return;
    }

    setFeatureLoading(true);
    setStatusMessage('Thinking…');

    try {
      const response = await sendChatMessage(input);
      if (response.reply) {
        setMessages((msgs) => [...msgs, { role: 'assistant', content: response.reply }]);
      }

      if (Array.isArray(response.suggestions)) {
        setChatPrompts(response.suggestions);
      }

      if (response.feature) {
        setFeatureResult(response.feature);
      } else if (response.featureId) {
        try {
          const fetched = await fetchFeature(response.featureId);
          setFeatureResult(fetched);
        } catch (error) {
          setMessages((msgs) => [
            ...msgs,
            { role: 'assistant', content: `I had trouble fetching that data: ${error.message}` }
          ]);
        }
      }

      setStatusMessage('Done.');
    } catch (error) {
      setMessages((msgs) => [
        ...msgs,
        { role: 'assistant', content: error.message }
      ]);
      setStatusMessage('Something went wrong.');
    } finally {
      setFeatureLoading(false);
    }
  };

  if (session.loading) {
    return (
      <div className="loading-screen">
        <p>Loading…</p>
      </div>
    );
  }

  if (!isLoggedIn) {
    return (
      <div className="app-shell">
        <LoginForm onSubmit={handleLogin} loading={loginPending} error={loginError} />
        <StatusBar message={statusMessage} />
      </div>
    );
  }

  const currentGameweek = featureResult?.metadata?.gameweek ?? session.data?.current_gameweek ?? '—';

  return (
    <div className="app-shell soccer-theme">
      <header className="stadium-header">
        <div className="stadium-banner">
          <div className="club-crest">FPL</div>
          <div className="header-text">
            <h1>FPL Dugout</h1>
            <p>{userName ? `Manager: ${userName}` : 'Virtual Touchline Assistant'}</p>
          </div>
          <div className="header-meta">
            <span className="score-chip">GW {currentGameweek}</span>
            <button type="button" className="header-action" onClick={handleLogout}>
              Sign Out
            </button>
          </div>
        </div>
      </header>

      <div className="app-content-pitch">
        <div className="chat-column">
          <ChatInterface
            messages={messages}
            prompts={chatPrompts}
            onPromptClick={(prompt) => handleChatMessage(prompt.promptText || prompt.label)}
            onSubmit={handleChatMessage}
            disabled={featureLoading}
            title="Touchline Coach"
            subtitle={userName ? `${userName}'s technical area` : 'Your virtual dugout'}
          />
        </div>
        <section className="analysis-board">
          <FeatureContent result={featureResult} loading={featureLoading} />
        </section>
      </div>
      <StatusBar message={statusMessage} />
    </div>
  );
}
