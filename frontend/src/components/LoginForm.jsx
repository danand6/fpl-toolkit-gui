import { useState } from 'react';

const extractId = (raw) => {
  if (!raw) return '';
  const match = String(raw).match(/(\d{3,})/);
  return match ? match[1] : String(raw).replace(/[^0-9]/g, '');
};

export default function LoginForm({ onSubmit, loading, error }) {
  const [teamId, setTeamId] = useState('');
  const [leagueId, setLeagueId] = useState('');
  const [teamSearch, setTeamSearch] = useState('');
  const [teamResults, setTeamResults] = useState([]);
  const [teamSearchLoading, setTeamSearchLoading] = useState(false);
  const [teamSearchError, setTeamSearchError] = useState('');

  const handleSubmit = (event) => {
    event.preventDefault();
    if (!teamId || !leagueId) {
      return;
    }
    onSubmit(teamId, leagueId);
  };

  const handleTeamSearch = async () => {
    const query = teamSearch.trim();
    if (query.length < 3) {
      setTeamSearchError('Enter at least 3 characters.');
      setTeamResults([]);
      return;
    }
    setTeamSearchError('');
    setTeamSearchLoading(true);
    try {
      const response = await fetch(`/api/search/entries?q=${encodeURIComponent(query)}`);
      if (!response.ok) {
        throw new Error('Search failed');
      }
      const data = await response.json();
      setTeamResults(Array.isArray(data.entries) ? data.entries : []);
    } catch (err) {
      setTeamSearchError(err.message || 'Search failed');
      setTeamResults([]);
    } finally {
      setTeamSearchLoading(false);
    }
  };

  const handleSelectTeam = (entry) => {
    setTeamId(String(entry.id));
    setTeamSearch(`${entry.team_name} (${entry.manager_name})`);
    setTeamResults([]);
  };

  return (
    <div className="login-container">
      <div className="login-card">
        <h1>FPL Toolkit</h1>
        <p className="login-subtitle">Sign in with your FPL Team and League IDs</p>
        <form onSubmit={handleSubmit}>
          <label htmlFor="team-id">Team ID</label>
          <input
            id="team-id"
            type="text"
            value={teamId}
            onChange={(event) => setTeamId(extractId(event.target.value))}
            placeholder="Paste team URL or ID"
            required
          />
          <span className="login-hint">Tip: paste the link to your squad page and we’ll grab the number.</span>

          <div className="login-search">
            <input
              type="text"
              value={teamSearch}
              onChange={(event) => setTeamSearch(event.target.value)}
              placeholder="Or search by team / manager name"
              aria-label="Search team name"
            />
            <button type="button" onClick={handleTeamSearch} disabled={teamSearchLoading}>
              {teamSearchLoading ? 'Searching…' : 'Search'}
            </button>
          </div>
          {teamSearchError ? <p className="login-error">{teamSearchError}</p> : null}
          {teamResults.length ? (
            <ul className="login-results">
              {teamResults.map((entry) => (
                <li key={entry.id}>
                  <button type="button" onClick={() => handleSelectTeam(entry)}>
                    <span className="result-team">{entry.team_name}</span>
                    <span className="result-manager">{entry.manager_name}</span>
                    <span className="result-id">#{entry.id}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}

          <label htmlFor="league-id">League ID</label>
          <input
            id="league-id"
            type="text"
            value={leagueId}
            onChange={(event) => setLeagueId(extractId(event.target.value))}
            placeholder="Paste mini-league URL or ID"
            required
          />
          <span className="login-hint">Works with any classic league standings URL.</span>

          <button type="submit" disabled={loading}>
            {loading ? 'Verifying…' : 'Continue'}
          </button>
        </form>
        {error ? <p className="error-text">{error}</p> : null}
      </div>
    </div>
  );
}
