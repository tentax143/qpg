import axios from 'axios';

// Public domains where the API is served same-origin (behind the proxy).
const PROD_HOSTS = ['qgen.ramcoad.com', 'questionpapergeneration.duckdns.org'];
// Port the Django backend listens on for local / LAN access.
const LOCAL_API_PORT = 1223;

// Resolve the backend base URL at runtime from where the frontend is loaded,
// so a single build works both for clients (qgen.ramcoad.com) and for local
// access via localhost / the LAN IP.
function resolveApiBaseURL() {
  // SSR / build time: no window — fall back to the env value or prod.
  if (typeof window === 'undefined') {
    return process.env.NEXT_PUBLIC_API_URL || 'https://qgen.ramcoad.com/api';
  }
  const { protocol, hostname, origin } = window.location;
  // Client on a public domain -> same-origin API (proxy forwards /api to Django).
  if (PROD_HOSTS.includes(hostname)) {
    return `${origin}/api`;
  }
  // Local / LAN dev -> Django on the same host, port 1223.
  return `${protocol}//${hostname}:${LOCAL_API_PORT}/api`;
}

const apiClient = axios.create({
  baseURL: resolveApiBaseURL(),
  withCredentials: true,
  xsrfCookieName: 'csrftoken',
  xsrfHeaderName: 'X-CSRFToken',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Session timeout in milliseconds (24 hours — matches backend SESSION_COOKIE_AGE)
const SESSION_TIMEOUT = 24 * 3600 * 1000;

// Add request interceptor for auth token and session expiration
apiClient.interceptors.request.use(
  (config) => {
    // Resolve the backend URL per-request so it always matches the current host.
    config.baseURL = resolveApiBaseURL();

    // Skip session check for auth endpoints
    if (config.url.startsWith('/auth/login') || config.url.startsWith('/auth/logout')) {
      return config;
    }

    // Check for session expiration
    const loginTimestamp = localStorage.getItem('loginTimestamp');
    if (loginTimestamp) {
      const now = Date.now();
      if (now - parseInt(loginTimestamp) > SESSION_TIMEOUT) {
        // Session expired
        localStorage.removeItem('authToken');
        localStorage.removeItem('user');
        localStorage.removeItem('loginTimestamp');
        if (typeof window !== 'undefined') {
          window.location.href = '/login?expired=true';
          // Cancel request
          const controller = new AbortController();
          config.signal = controller.signal;
          controller.abort();
          return config;
        }
      }
    }

    const token = localStorage.getItem('authToken');
    if (token) {
      // Django Token Authentication uses "Token" prefix
      config.headers.Authorization = `Token ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Add response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    // Check key authentication errors
    if (error.response?.status === 401 || error.response?.status === 403) {
      // Only redirect if we are not already on the login/register pages
      if (typeof window !== 'undefined' && 
          !window.location.pathname.startsWith('/login') && 
          !window.location.pathname.startsWith('/register')) {
        
        localStorage.removeItem('authToken');
        localStorage.removeItem('user');
        localStorage.removeItem('loginTimestamp');
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default apiClient;
