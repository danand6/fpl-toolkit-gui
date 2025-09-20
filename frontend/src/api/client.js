import { FEATURE_BY_ID } from '../constants/features.js';

async function parseResponse(response) {
  const contentType = response.headers.get('content-type');
  let payload;

  if (contentType && contentType.includes('application/json')) {
    payload = await response.json();
  } else {
    payload = await response.text();
  }

  if (!response.ok) {
    const message = payload?.error || response.statusText || 'Request failed';
    throw new Error(message);
  }

  return payload;
}

export async function getSession() {
  const response = await fetch('/api/session');
  return parseResponse(response);
}

export async function login(teamId, leagueId) {
  const response = await fetch('/api/login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ team_id: Number(teamId), league_id: Number(leagueId) })
  });

  return parseResponse(response);
}

export async function logout() {
  const response = await fetch('/api/logout', { method: 'POST' });
  return parseResponse(response);
}

export async function sendChatMessage(message) {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ message })
  });

  return parseResponse(response);
}

function buildUrl(endpoint, params) {
  if (!params || Object.keys(params).length === 0) {
    return endpoint;
  }

  const search = new URLSearchParams(params);
  return `${endpoint}?${search.toString()}`;
}

export async function fetchFeature(featureId, params = {}) {
  const feature = FEATURE_BY_ID[featureId];
  if (!feature || !feature.endpoint) {
    throw new Error('Unknown feature.');
  }

  const response = await fetch(buildUrl(feature.endpoint, params));
  return parseResponse(response);
}
