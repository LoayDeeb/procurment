import axios from 'axios';
import { API_BASE } from './api';

export const apiClient = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
});

export function formatApiError(error, fallbackMessage) {
  if (error?.response?.data?.detail) {
    return String(error.response.data.detail);
  }
  if (error?.code === 'ECONNABORTED') {
    return 'Request timed out. Please retry.';
  }
  if (error?.message) {
    return error.message;
  }
  return fallbackMessage;
}
