import { createContext, useContext, useState, useEffect, type ReactNode, useCallback } from 'react';
import type { User } from '../api/auth';
import { getAuthToken, getCurrentUser, clearAuthToken } from '../api/auth';

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (data: { full_name: string; email: string; password: string; role?: 'citizen' | 'officer' }) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const loadUser = useCallback(async () => {
    const token = getAuthToken();
    if (token) {
      try {
        const userData = await getCurrentUser(token);
        setUser(userData);
      } catch {
        clearAuthToken();
        setUser(null);
      }
    }
    setIsLoading(false);
  }, []);

  useEffect(() => {
    loadUser();
  }, [loadUser]);

  const login = async (email: string, password: string) => {
    const { loginUser, saveAuthToken } = await import('../api/auth');
    const tokens = await loginUser({ email, password });
    saveAuthToken(tokens.access_token);
    const userData = await getCurrentUser(tokens.access_token);
    setUser(userData);
  };

  const register = async (data: { full_name: string; email: string; password: string; role?: 'citizen' | 'officer' }) => {
    const { registerUser, loginUser, saveAuthToken } = await import('../api/auth');
    await registerUser(data);
    const tokens = await loginUser({ email: data.email, password: data.password });
    saveAuthToken(tokens.access_token);
    const userData = await getCurrentUser(tokens.access_token);
    setUser(userData);
  };

  const logout = () => {
    clearAuthToken();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, isLoading, login, register, logout, isAuthenticated: !!user }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}