import axios from 'axios';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';

const apiClient = axios.create({
  baseURL: API_URL,
  withCredentials: true,
  xsrfCookieName: 'csrftoken',
  xsrfHeaderName: 'X-CSRFToken',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Session timeout in milliseconds (1 hour to match backend SESSION_COOKIE_AGE)
const SESSION_TIMEOUT = 3600 * 1000;

// Add request interceptor for auth token and session expiration
apiClient.interceptors.request.use(
  (config) => {
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
