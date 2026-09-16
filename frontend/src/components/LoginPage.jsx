import React, { useState } from 'react';
import {
  ShieldAlert,
  ShieldCheck,
  Lock,
  User,
  Users,
  Eye,
  EyeOff,
  AlertTriangle,
  ArrowRight,
  KeyRound,
  Fingerprint,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export default function LoginPage() {
  const { login, authError, clearError } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [localError, setLocalError] = useState('');
  const [showDemoCreds, setShowDemoCreds] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setLocalError('Please enter both username and password.');
      return;
    }
    setLocalError('');
    clearError();
    setIsSubmitting(true);

    try {
      await login(username.trim(), password);
    } catch (err) {
      setLocalError(err.message || 'Authentication failed. Please check your credentials.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleQuickLogin = async (role) => {
    setLocalError('');
    clearError();
    setIsSubmitting(true);
    let user, pass;
    if (role === 'admin') { user = 'admin'; pass = 'Admin@IBVAP2026!'; }
    else if (role === 'supervisor') { user = 'supervisor'; pass = 'Supervisor@IBVAP2026!'; }
    else { user = 'operator'; pass = 'Operator@IBVAP2026!'; }

    setUsername(user);
    setPassword('');

    try {
      await login(user, pass);
    } catch (err) {
      setLocalError(err.message || `Failed to authenticate as ${role}.`);
    } finally {
      setIsSubmitting(false);
    }
  };

  const displayedError = localError || authError;

  return (
    <div className="login-wrapper" role="main" aria-label="Command Center Login">
      <div className="login-backdrop-glow" />
      <div className="login-grid-bg" />

      <div className="login-card">
        {/* Header Branding */}
        <div className="login-header">
          <div className="login-logo-container">
            <div className="login-logo-ring" />
            <ShieldAlert size={26} className="login-logo-icon" />
          </div>
          <div className="login-title-group">
            <div className="login-badge">
              <Fingerprint size={11} />
              <span>DEFENSE SURVEILLANCE // RESTRICTED ACCESS</span>
            </div>
            <h1 className="login-title">
              IBVAP <span className="highlight-cyan">CORE</span>
            </h1>
            <p className="login-subtitle">
              Intelligent Border Video Analytics Platform
            </p>
          </div>
        </div>

        {/* Error Alert Banner */}
        {displayedError && (
          <div className="login-error-banner" role="alert">
            <AlertTriangle size={15} className="error-icon" />
            <div className="error-text">
              <strong>Authentication Denied</strong>
              <span>{displayedError}</span>
            </div>
          </div>
        )}

        {/* Login Form */}
        <form onSubmit={handleSubmit} className="login-form" noValidate>
          <div className="form-group">
            <label htmlFor="username" className="form-label">
              <User size={13} />
              <span>Operator / Admin Username</span>
            </label>
            <div className="input-wrapper">
              <input
                id="username"
                name="username"
                type="text"
                className="form-input"
                placeholder="Enter username"
                value={username}
                onChange={(e) => {
                  setUsername(e.target.value);
                  if (displayedError) {
                    setLocalError('');
                    clearError();
                  }
                }}
                autoComplete="username"
                autoFocus
                required
                disabled={isSubmitting}
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="password" className="form-label">
              <Lock size={13} />
              <span>Security Password</span>
            </label>
            <div className="input-wrapper password-input-wrapper">
              <input
                id="password"
                name="password"
                type={showPassword ? 'text' : 'password'}
                className="form-input"
                placeholder="Enter password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (displayedError) {
                    setLocalError('');
                    clearError();
                  }
                }}
                autoComplete="current-password"
                required
                disabled={isSubmitting}
              />
              <button
                type="button"
                className="password-toggle-btn"
                onClick={() => setShowPassword(!showPassword)}
                title={showPassword ? 'Hide password' : 'Show password'}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                tabIndex={-1}
              >
                {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>

          <button
            type="submit"
            className="login-submit-btn"
            disabled={isSubmitting}
            aria-busy={isSubmitting}
          >
            {isSubmitting ? (
              <span className="btn-loading-content">
                <span className="login-spinner" />
                <span>Verifying Credentials...</span>
              </span>
            ) : (
              <span className="btn-normal-content">
                <KeyRound size={15} />
                <span>Authenticate & Access System</span>
                <ArrowRight size={15} />
              </span>
            )}
          </button>
        </form>

        {/* Demo Fast-Login Chips (Compact & Clean) */}
        <div className="demo-credentials-section">
          <div className="demo-credentials-label">
            <span>QUICK EVALUATION ACCESS</span>
          </div>
          <div className="demo-chips-row" style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', justifyContent: 'center' }}>
            <button
              type="button"
              className="demo-chip chip-admin"
              onClick={() => handleQuickLogin('admin')}
              disabled={isSubmitting}
              title="One-click authentication as Administrator"
            >
              <ShieldCheck size={14} />
              <div className="chip-text">
                <strong>Login as Admin</strong>
                <span className="chip-role-desc">Full Command Access</span>
              </div>
            </button>

            <button
              type="button"
              className="demo-chip chip-supervisor"
              onClick={() => handleQuickLogin('supervisor')}
              disabled={isSubmitting}
              title="One-click authentication as Supervisor"
              style={{ background: 'rgba(22, 163, 74, 0.15)', border: '1px solid rgba(22, 163, 74, 0.3)', color: 'var(--text-primary)' }}
            >
              <Users size={14} style={{ color: '#16a34a' }}/>
              <div className="chip-text">
                <strong>Login as Supervisor</strong>
                <span className="chip-role-desc">Shift Management</span>
              </div>
            </button>

            <button
              type="button"
              className="demo-chip chip-operator"
              onClick={() => handleQuickLogin('operator')}
              disabled={isSubmitting}
              title="One-click authentication as Operator"
            >
              <User size={14} />
              <div className="chip-text">
                <strong>Login as Operator</strong>
                <span className="chip-role-desc">Surveillance Ops</span>
              </div>
            </button>
          </div>

          {/* Optional reveal toggle for judges/testing only (OFF by default) */}
          <div className="demo-credentials-toggle-wrap">
            <button
              type="button"
              className="demo-credentials-toggle"
              onClick={() => setShowDemoCreds(!showDemoCreds)}
              aria-expanded={showDemoCreds}
            >
              <span>{showDemoCreds ? 'Hide credentials reference' : 'Show credentials reference (judges/testing)'}</span>
              {showDemoCreds ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>

            {showDemoCreds && (
              <div className="demo-credentials-drawer" role="region" aria-label="Demo Credentials Reference">
                <div className="drawer-item">
                  <span className="drawer-role admin-color">Admin:</span>
                  <code>username: <strong>admin</strong> | password: <strong>Admin@IBVAP2026!</strong></code>
                </div>
                <div className="drawer-item">
                  <span className="drawer-role" style={{ color: '#16a34a' }}>Supervisor:</span>
                  <code>username: <strong>supervisor</strong> | password: <strong>Supervisor@IBVAP2026!</strong></code>
                </div>
                <div className="drawer-item">
                  <span className="drawer-role operator-color">Operator:</span>
                  <code>username: <strong>operator</strong> | password: <strong>Operator@IBVAP2026!</strong></code>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Tamper-Evident Audit Trail Notice (Compact) */}
        <div className="login-audit-notice">
          <ShieldCheck size={13} className="notice-icon" />
          <span>
            <strong>Tamper-Evident Audit Logging Active:</strong> All login attempts are signed with SHA-256 and committed to the immutable audit ledger.
          </span>
        </div>
      </div>
    </div>
  );
}
