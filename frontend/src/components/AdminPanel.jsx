import React, { useState, useEffect, useRef } from 'react';
import {
  ShieldCheck,
  ShieldAlert,
  Users,
  Car,
  Plus,
  Trash2,
  RefreshCw,
  Search,
  Calendar,
  FileText,
  Upload,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Lock,
  X,
  Eye,
  Camera,
  Layers,
  Sparkles,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import {
  fetchWatchlist,
  addWatchlistPerson,
  deleteWatchlistPerson,
  rescanWatchlist,
  getWatchlistPhotoUrl,
  fetchVehicles,
  addVehicle,
  deleteVehicle,
} from '../services/api';

export default function AdminPanel({ isSupervisorMode = false }) {
  const { user, isAdmin } = useAuth();
  const [activeTab, setActiveTab] = useState('personnel'); // 'personnel' | 'vehicles'

  // Watchlist State
  const [watchlist, setWatchlist] = useState([]);
  const [loadingWatchlist, setLoadingWatchlist] = useState(false);
  const [personSearch, setPersonSearch] = useState('');
  const [personStatusFilter, setPersonStatusFilter] = useState('all');

  // Watchlist Form State
  const [personName, setPersonName] = useState('');
  const [personRole, setPersonRole] = useState('SSB Personnel');
  const [personExpiry, setPersonExpiry] = useState('');
  const [personNotes, setPersonNotes] = useState('');
  const [personPhoto, setPersonPhoto] = useState(null);
  const [personPhotoPreview, setPersonPhotoPreview] = useState('');
  const [savingPerson, setSavingPerson] = useState(false);

  // Vehicle Whitelist State
  const [vehicles, setVehicles] = useState([]);
  const [loadingVehicles, setLoadingVehicles] = useState(false);
  const [vehicleSearch, setVehicleSearch] = useState('');
  const [vehicleStatusFilter, setVehicleStatusFilter] = useState('all');

  // Vehicle Form State
  const [plateNumber, setPlateNumber] = useState('');
  const [ownerName, setOwnerName] = useState('');
  const [vehicleType, setVehicleType] = useState('Patrol Jeep');
  const [purpose, setPurpose] = useState('Sector 4 Perimeter Patrol');
  const [vehicleExpiry, setVehicleExpiry] = useState('');
  const [vehicleNotes, setVehicleNotes] = useState('');
  const [savingVehicle, setSavingVehicle] = useState(false);

  // Rescan state
  const [isRescanning, setIsRescanning] = useState(false);
  const [rescanResult, setRescanResult] = useState(null);

  // Feedback Notification Banner
  const [notification, setNotification] = useState(null);

  // Modal for viewing full photo
  const [previewModalImg, setPreviewModalImg] = useState(null);

  const fileInputRef = useRef(null);

  const showNotification = (type, message) => {
    setNotification({ type, message });
    setTimeout(() => {
      setNotification((curr) => (curr?.message === message ? null : curr));
    }, 5000);
  };

  // Load Watchlist Data
  const loadWatchlistData = async () => {
    setLoadingWatchlist(true);
    try {
      const data = await fetchWatchlist();
      setWatchlist(data.watchlist || []);
    } catch (err) {
      showNotification('error', err.message || 'Failed to load watchlist profiles');
    } finally {
      setLoadingWatchlist(false);
    }
  };

  // Load Vehicle Data
  const loadVehicleData = async () => {
    setLoadingVehicles(true);
    try {
      const data = await fetchVehicles();
      setVehicles(data.vehicles || []);
    } catch (err) {
      showNotification('error', err.message || 'Failed to load authorized vehicles');
    } finally {
      setLoadingVehicles(false);
    }
  };

  useEffect(() => {
    if (isAdmin) {
      loadWatchlistData();
      loadVehicleData();
    }
  }, [isAdmin]);

  // Handle Photo selection
  const handlePhotoChange = (e) => {
    const file = e.target.files?.[0];
    if (file) {
      setPersonPhoto(file);
      const previewUrl = URL.createObjectURL(file);
      setPersonPhotoPreview(previewUrl);
    }
  };

  // Submit Person Form
  const handleSavePerson = async (e) => {
    e.preventDefault();
    if (!personName.trim()) {
      showNotification('error', 'Please enter a name for the personnel profile.');
      return;
    }
    if (!personPhoto && !personPhotoPreview) {
      showNotification('error', 'Please upload a reference portrait photo for facial recognition.');
      return;
    }

    setSavingPerson(true);
    try {
      const formData = new FormData();
      formData.append('name', personName.trim());
      formData.append('role', personRole);
      if (personExpiry) formData.append('expiry_date', personExpiry);
      if (personNotes) formData.append('notes', personNotes.trim());
      if (personPhoto) formData.append('photo', personPhoto);

      const res = await addWatchlistPerson(formData);
      showNotification('success', res.message || `Profile '${personName}' saved successfully!`);
      
      // Reset form
      setPersonName('');
      setPersonRole('SSB Personnel');
      setPersonExpiry('');
      setPersonNotes('');
      setPersonPhoto(null);
      setPersonPhotoPreview('');
      if (fileInputRef.current) fileInputRef.current.value = '';

      await loadWatchlistData();
    } catch (err) {
      showNotification('error', err.message || 'Failed to save watchlist person');
    } finally {
      setSavingPerson(false);
    }
  };

  // Delete Person
  const handleDeletePerson = async (name) => {
    if (!window.confirm(`Are you sure you want to remove '${name}' from the authorized watchlist?`)) {
      return;
    }
    try {
      await deleteWatchlistPerson(name);
      showNotification('success', `Watchlist profile '${name}' removed.`);
      await loadWatchlistData();
    } catch (err) {
      showNotification('error', err.message || 'Failed to delete watchlist person');
    }
  };

  // Submit Vehicle Form
  const handleSaveVehicle = async (e) => {
    e.preventDefault();
    if (!plateNumber.trim()) {
      showNotification('error', 'Please enter a vehicle license plate number.');
      return;
    }
    if (!ownerName.trim()) {
      showNotification('error', 'Please specify the vehicle owner or battalion unit.');
      return;
    }

    setSavingVehicle(true);
    try {
      const payload = {
        plate_number: plateNumber.trim().toUpperCase(),
        owner_name: ownerName.trim(),
        vehicle_type: vehicleType,
        purpose: purpose.trim(),
        expiry_date: vehicleExpiry || null,
        notes: vehicleNotes.trim() || null,
      };

      const res = await addVehicle(payload);
      showNotification('success', res.message || `Vehicle '${payload.plate_number}' added to whitelist!`);

      // Reset form
      setPlateNumber('');
      setOwnerName('');
      setVehicleType('Patrol Jeep');
      setPurpose('Sector 4 Perimeter Patrol');
      setVehicleExpiry('');
      setVehicleNotes('');

      await loadVehicleData();
    } catch (err) {
      showNotification('error', err.message || 'Failed to add authorized vehicle');
    } finally {
      setSavingVehicle(false);
    }
  };

  // Delete Vehicle
  const handleDeleteVehicle = async (plate) => {
    if (!window.confirm(`Are you sure you want to remove vehicle '${plate}' from the whitelist?`)) {
      return;
    }
    try {
      await deleteVehicle(plate);
      showNotification('success', `Vehicle '${plate}' removed from whitelist.`);
      await loadVehicleData();
    } catch (err) {
      showNotification('error', err.message || 'Failed to delete vehicle');
    }
  };

  // Watchlist Rescan Trigger
  const handleRescanWatchlist = async () => {
    setIsRescanning(true);
    setRescanResult(null);
    try {
      const res = await rescanWatchlist();
      setRescanResult(res);
      showNotification('success', `Watchlist Re-scanned: ${res.profiles_loaded} profiles cached into memory.`);
      await loadWatchlistData();
    } catch (err) {
      showNotification('error', err.message || 'Failed to rescan watchlist');
    } finally {
      setIsRescanning(false);
    }
  };

  // Filtering Watchlist
  const filteredWatchlist = watchlist.filter((item) => {
    const matchesSearch =
      item.name.toLowerCase().includes(personSearch.toLowerCase()) ||
      (item.role && item.role.toLowerCase().includes(personSearch.toLowerCase())) ||
      (item.notes && item.notes.toLowerCase().includes(personSearch.toLowerCase()));

    if (personStatusFilter === 'active') return matchesSearch && !item.is_expired;
    if (personStatusFilter === 'expired') return matchesSearch && item.is_expired;
    return matchesSearch;
  });

  // Filtering Vehicles
  const filteredVehicles = vehicles.filter((v) => {
    const matchesSearch =
      v.plate_number.toLowerCase().includes(vehicleSearch.toLowerCase()) ||
      v.owner_name.toLowerCase().includes(vehicleSearch.toLowerCase()) ||
      (v.vehicle_type && v.vehicle_type.toLowerCase().includes(vehicleSearch.toLowerCase())) ||
      (v.purpose && v.purpose.toLowerCase().includes(vehicleSearch.toLowerCase()));

    if (vehicleStatusFilter === 'active') return matchesSearch && !v.is_expired;
    if (vehicleStatusFilter === 'expired') return matchesSearch && v.is_expired;
    return matchesSearch;
  });

  // Non-Admin Access Denied Screen
  if (!isAdmin) {
    return (
      <div className="admin-access-denied">
        <div className="denied-card">
          <div className="denied-icon-wrap">
            <Lock size={48} className="lock-icon" />
          </div>
          <h2>Administrative Clearance Required</h2>
          <p>
            The Admin Command Panel is restricted strictly to users with the <code>admin</code> role.
            Your current session role is <code>{user?.role || 'operator'}</code>.
          </p>
          <div className="denied-hint">
            To manage watchlist personnel or vehicle whitelists, please sign in with administrative credentials.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-panel-container">
      {/* Top Admin Header Bar */}
      <div className="admin-top-header">
        <div className="admin-header-title-block">
          <div className="admin-header-icon">
            <ShieldCheck size={24} style={{ color: '#0ea5e9' }} />
          </div>
          <div>
            <div className="admin-title">
              Admin Command & Clearance Registry
              <span className="admin-role-badge">ADMIN ACCESS ACTIVE</span>
            </div>
            <div className="admin-subtitle">
              Manage authorized personnel facial identification profiles and ANPR vehicle whitelists with automated access control & expiration governance.
            </div>
          </div>
        </div>

        <div className="admin-header-actions">
          <button
            type="button"
            className={`rescan-btn ${isRescanning ? 'loading' : ''}`}
            onClick={handleRescanWatchlist}
            disabled={isRescanning}
            title="Re-scan backend/watchlist/ folder and regenerate all facial embeddings in memory without restarting server"
          >
            <RefreshCw size={16} className={isRescanning ? 'spin-icon' : ''} />
            <span>{isRescanning ? 'RE-SCANNING...' : 'RE-SCAN WATCHLIST'}</span>
          </button>
        </div>
      </div>

      {/* Notification Toast Banner */}
      {notification && (
        <div className={`admin-notification-toast ${notification.type}`}>
          {notification.type === 'success' ? (
            <CheckCircle2 size={18} />
          ) : (
            <AlertTriangle size={18} />
          )}
          <span className="toast-msg">{notification.message}</span>
          <button
            type="button"
            className="toast-close"
            onClick={() => setNotification(null)}
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Primary Sub-Navigation Tabs */}
      <div className="admin-tabs-nav">
        <button
          type="button"
          className={`admin-subtab-btn ${activeTab === 'personnel' ? 'active' : ''}`}
          onClick={() => setActiveTab('personnel')}
        >
          <Users size={18} />
          <span>Authorized Personnel Watchlist</span>
          <span className="tab-pill-count">{watchlist.length}</span>
        </button>

        <button
          type="button"
          className={`admin-subtab-btn ${activeTab === 'vehicles' ? 'active' : ''}`}
          onClick={() => setActiveTab('vehicles')}
        >
          <Car size={18} />
          <span>Authorized Vehicles Whitelist</span>
          <span className="tab-pill-count">{vehicles.length}</span>
        </button>
      </div>

      {/* TAB 1: PERSONNEL WATCHLIST MANAGEMENT */}
      {activeTab === 'personnel' && (
        <div className="admin-tab-content">
          <div className="admin-grid-layout">
            {/* Form Column: Add New Profile */}
            <div className="admin-form-card">
              <div className="card-header-line">
                <div className="card-title-group">
                  <Plus size={18} className="icon-cyan" />
                  <h3>Register Authorized Personnel</h3>
                </div>
                <span className="card-tag">Biometric Profile</span>
              </div>
              <p className="card-desc">
                Upload a portrait image to extract a 128-d SFace embedding for facial recognition.
              </p>

              <form onSubmit={handleSavePerson} className="admin-entry-form">
                {/* Photo Upload Zone */}
                <div className="form-group">
                  <label className="form-label">Reference Portrait Photo *</label>
                  <div
                    className={`photo-drop-zone ${personPhotoPreview ? 'has-preview' : ''}`}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <input
                      type="file"
                      ref={fileInputRef}
                      onChange={handlePhotoChange}
                      accept="image/png,image/jpeg,image/jpg,image/webp"
                      style={{ display: 'none' }}
                    />
                    {personPhotoPreview ? (
                      <div className="preview-container">
                        <img src={personPhotoPreview} alt="Preview" className="photo-preview-img" />
                        <div className="preview-overlay">
                          <Camera size={18} />
                          <span>Change Photo</span>
                        </div>
                      </div>
                    ) : (
                      <div className="drop-prompt">
                        <Upload size={28} className="drop-icon" />
                        <span className="drop-title">Click to upload portrait</span>
                        <span className="drop-sub">PNG, JPG, or WEBP (Clear frontal face)</span>
                      </div>
                    )}
                  </div>
                </div>

                <div className="form-group">
                  <label className="form-label">Full Name *</label>
                  <input
                    type="text"
                    className="admin-text-input"
                    placeholder="e.g. Capt. Kunal Singh"
                    value={personName}
                    onChange={(e) => setPersonName(e.target.value)}
                    required
                  />
                </div>

                <div className="form-row">
                  <div className="form-group flex-1">
                    <label className="form-label">Role / Category</label>
                    <select
                      className="admin-select-input"
                      value={personRole}
                      onChange={(e) => setPersonRole(e.target.value)}
                    >
                      <option value="SSB Personnel">SSB Personnel</option>
                      <option value="Border Patrol Officer">Border Patrol Officer</option>
                      <option value="Command Staff">Command Staff</option>
                      <option value="Surveillance Operator">Surveillance Operator</option>
                      <option value="Contractor">Contractor</option>
                      <option value="Visitor">Visitor</option>
                      <option value="Medical Officer">Medical Officer</option>
                    </select>
                  </div>

                  <div className="form-group flex-1">
                    <label className="form-label">
                      Expiry Date
                      <span className="label-sub">(Optional)</span>
                    </label>
                    <input
                      type="date"
                      className="admin-date-input"
                      value={personExpiry}
                      onChange={(e) => setPersonExpiry(e.target.value)}
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label className="form-label">
                    Operational Notes
                    <span className="label-sub">(Optional)</span>
                  </label>
                  <textarea
                    className="admin-textarea"
                    rows={2}
                    placeholder="e.g. Sector 4 QRT Leader, Gate Pass #B-88"
                    value={personNotes}
                    onChange={(e) => setPersonNotes(e.target.value)}
                  />
                </div>

                <button
                  type="submit"
                  className="admin-submit-btn"
                  disabled={savingPerson}
                >
                  <ShieldCheck size={16} />
                  <span>{savingPerson ? 'Saving & Generating Embeddings...' : 'Save Watchlist Profile'}</span>
                </button>
              </form>
            </div>

            {/* List Column: Active Profiles Table */}
            <div className="admin-list-card">
              <div className="card-header-line">
                <div className="card-title-group">
                  <Users size={18} className="icon-cyan" />
                  <h3>Active Personnel Registry ({filteredWatchlist.length})</h3>
                </div>
                <div className="header-filter-group">
                  <div className="search-box">
                    <Search size={14} className="search-icon" />
                    <input
                      type="text"
                      placeholder="Search name, role..."
                      value={personSearch}
                      onChange={(e) => setPersonSearch(e.target.value)}
                    />
                  </div>
                  <select
                    className="status-filter-select"
                    value={personStatusFilter}
                    onChange={(e) => setPersonStatusFilter(e.target.value)}
                  >
                    <option value="all">All Statuses</option>
                    <option value="active">Active Only</option>
                    <option value="expired">Expired Only</option>
                  </select>
                </div>
              </div>

              {loadingWatchlist ? (
                <div className="table-loading-state">
                  <RefreshCw size={24} className="spin-icon" />
                  <span>Loading watchlist profiles...</span>
                </div>
              ) : filteredWatchlist.length === 0 ? (
                <div className="table-empty-state">
                  <Users size={36} style={{ opacity: 0.3 }} />
                  <p>No watchlist profiles match the search criteria.</p>
                </div>
              ) : (
                <div className="admin-table-wrapper">
                  <table className="admin-data-table">
                    <thead>
                      <tr>
                        <th>Portrait</th>
                        <th>Name</th>
                        <th>Role / Unit</th>
                        <th>Clearance Status</th>
                        <th>Expiry Date</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredWatchlist.map((person) => (
                        <tr key={person.name} className={person.is_expired ? 'row-expired' : ''}>
                          <td className="cell-photo">
                            <div
                              className="table-photo-thumb"
                              onClick={() => setPreviewModalImg(getWatchlistPhotoUrl(person.photo_filename))}
                              title="Click to view full portrait"
                            >
                              <img
                                src={getWatchlistPhotoUrl(person.photo_filename)}
                                alt={person.name}
                                onError={(e) => {
                                  e.target.style.display = 'none';
                                }}
                              />
                            </div>
                          </td>
                          <td className="cell-name">
                            <div className="name-primary">{person.name}</div>
                            {person.notes && <div className="name-notes">{person.notes}</div>}
                          </td>
                          <td className="cell-role">
                            <span className="role-chip">{person.role || 'Personnel'}</span>
                          </td>
                          <td className="cell-status">
                            {person.is_expired ? (
                              <span className="status-badge expired" title="Access revoked due to expired date">
                                <AlertTriangle size={12} />
                                EXPIRED
                              </span>
                            ) : (
                              <span className="status-badge active" title="Active authorized clearance">
                                <CheckCircle2 size={12} />
                                ACTIVE
                              </span>
                            )}
                          </td>
                          <td className="cell-expiry">
                            {person.expiry_date ? (
                              <div className="expiry-date-tag">
                                <Calendar size={12} />
                                <span>{person.expiry_date}</span>
                              </div>
                            ) : (
                              <span className="permanent-badge">PERMANENT</span>
                            )}
                          </td>
                          <td className="cell-actions">
                            <button
                              type="button"
                              className="action-del-btn"
                              onClick={() => handleDeletePerson(person.name)}
                              title={`Delete ${person.name} from watchlist`}
                            >
                              <Trash2 size={15} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: AUTHORIZED VEHICLES WHITELIST */}
      {activeTab === 'vehicles' && (
        <div className="admin-tab-content">
          <div className="admin-grid-layout">
            {/* Form Column: Add New Vehicle */}
            <div className="admin-form-card">
              <div className="card-header-line">
                <div className="card-title-group">
                  <Plus size={18} className="icon-cyan" />
                  <h3>Authorize Vehicle (ANPR)</h3>
                </div>
                <span className="card-tag">Plate Whitelist</span>
              </div>
              <p className="card-desc">
                Register authorized vehicle plate numbers. Matching ANPR detections will be categorized as routine low-severity access.
              </p>

              <form onSubmit={handleSaveVehicle} className="admin-entry-form">
                <div className="form-group">
                  <label className="form-label">License Plate Number *</label>
                  <input
                    type="text"
                    className="admin-text-input plate-input"
                    placeholder="e.g. DL 01 AB 1234"
                    value={plateNumber}
                    onChange={(e) => setPlateNumber(e.target.value.toUpperCase())}
                    required
                  />
                  <div className="input-hint">Spaces and hyphens are automatically normalized for ANPR matching.</div>
                </div>

                <div className="form-group">
                  <label className="form-label">Owner / Designated Unit *</label>
                  <input
                    type="text"
                    className="admin-text-input"
                    placeholder="e.g. Capt. Rajesh Kumar / Supply Unit 4"
                    value={ownerName}
                    onChange={(e) => setOwnerName(e.target.value)}
                    required
                  />
                </div>

                <div className="form-row">
                  <div className="form-group flex-1">
                    <label className="form-label">Vehicle Type</label>
                    <select
                      className="admin-select-input"
                      value={vehicleType}
                      onChange={(e) => setVehicleType(e.target.value)}
                    >
                      <option value="Patrol Jeep">Patrol Jeep</option>
                      <option value="Supply Truck">Supply Truck</option>
                      <option value="Medical Ambulance">Medical Ambulance</option>
                      <option value="Staff Car">Staff Car</option>
                      <option value="QRT Interceptor">QRT Interceptor</option>
                      <option value="Armored Carrier">Armored Carrier</option>
                      <option value="Commercial Delivery">Commercial Delivery</option>
                    </select>
                  </div>

                  <div className="form-group flex-1">
                    <label className="form-label">
                      Expiry Date
                      <span className="label-sub">(Optional)</span>
                    </label>
                    <input
                      type="date"
                      className="admin-date-input"
                      value={vehicleExpiry}
                      onChange={(e) => setVehicleExpiry(e.target.value)}
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label className="form-label">Operational Purpose</label>
                  <input
                    type="text"
                    className="admin-text-input"
                    placeholder="e.g. Sector 4 Perimeter Patrol"
                    value={purpose}
                    onChange={(e) => setPurpose(e.target.value)}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">
                    Operational Notes
                    <span className="label-sub">(Optional)</span>
                  </label>
                  <textarea
                    className="admin-textarea"
                    rows={2}
                    placeholder="e.g. Command Escort Unit, 24/7 Clearance"
                    value={vehicleNotes}
                    onChange={(e) => setVehicleNotes(e.target.value)}
                  />
                </div>

                <button
                  type="submit"
                  className="admin-submit-btn"
                  disabled={savingVehicle}
                >
                  <Car size={16} />
                  <span>{savingVehicle ? 'Saving Vehicle...' : 'Add Vehicle to Whitelist'}</span>
                </button>
              </form>
            </div>

            {/* List Column: Active Vehicles Table */}
            <div className="admin-list-card">
              <div className="card-header-line">
                <div className="card-title-group">
                  <Car size={18} className="icon-cyan" />
                  <h3>Authorized Vehicle Whitelist ({filteredVehicles.length})</h3>
                </div>
                <div className="header-filter-group">
                  <div className="search-box">
                    <Search size={14} className="search-icon" />
                    <input
                      type="text"
                      placeholder="Search plate, owner..."
                      value={vehicleSearch}
                      onChange={(e) => setVehicleSearch(e.target.value)}
                    />
                  </div>
                  <select
                    className="status-filter-select"
                    value={vehicleStatusFilter}
                    onChange={(e) => setVehicleStatusFilter(e.target.value)}
                  >
                    <option value="all">All Statuses</option>
                    <option value="active">Active Only</option>
                    <option value="expired">Expired Only</option>
                  </select>
                </div>
              </div>

              {loadingVehicles ? (
                <div className="table-loading-state">
                  <RefreshCw size={24} className="spin-icon" />
                  <span>Loading vehicle whitelist...</span>
                </div>
              ) : filteredVehicles.length === 0 ? (
                <div className="table-empty-state">
                  <Car size={36} style={{ opacity: 0.3 }} />
                  <p>No authorized vehicles match the search criteria.</p>
                </div>
              ) : (
                <div className="admin-table-wrapper">
                  <table className="admin-data-table">
                    <thead>
                      <tr>
                        <th>Plate Number</th>
                        <th>Owner / Battalion Unit</th>
                        <th>Vehicle Type & Purpose</th>
                        <th>Whitelist Status</th>
                        <th>Expiry Date</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredVehicles.map((v) => (
                        <tr key={v.plate_number} className={v.is_expired ? 'row-expired' : ''}>
                          <td className="cell-plate">
                            <div className="plate-badge-tactical">
                              <span className="plate-flag">IND</span>
                              <span className="plate-val">{v.plate_number}</span>
                            </div>
                          </td>
                          <td className="cell-owner">
                            <div className="owner-title">{v.owner_name}</div>
                            {v.notes && <div className="owner-notes">{v.notes}</div>}
                          </td>
                          <td className="cell-vtype">
                            <div className="vtype-title">{v.vehicle_type}</div>
                            <div className="vtype-purpose">{v.purpose}</div>
                          </td>
                          <td className="cell-status">
                            {v.is_expired ? (
                              <span className="status-badge expired" title="Pass expired; treated as unlisted vehicle">
                                <AlertTriangle size={12} />
                                EXPIRED
                              </span>
                            ) : (
                              <span className="status-badge active" title="Authorized routine access">
                                <CheckCircle2 size={12} />
                                AUTHORIZED
                              </span>
                            )}
                          </td>
                          <td className="cell-expiry">
                            {v.expiry_date ? (
                              <div className="expiry-date-tag">
                                <Calendar size={12} />
                                <span>{v.expiry_date}</span>
                              </div>
                            ) : (
                              <span className="permanent-badge">PERMANENT</span>
                            )}
                          </td>
                          <td className="cell-actions">
                            <button
                              type="button"
                              className="action-del-btn"
                              onClick={() => handleDeleteVehicle(v.plate_number)}
                              title={`Delete vehicle ${v.plate_number} from whitelist`}
                            >
                              <Trash2 size={15} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Modal for Full Photo Preview */}
      {previewModalImg && (
        <div className="photo-preview-modal-backdrop" onClick={() => setPreviewModalImg(null)}>
          <div className="photo-preview-modal" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className="modal-close-btn"
              onClick={() => setPreviewModalImg(null)}
            >
              <X size={18} />
            </button>
            <div className="modal-title">Watchlist Portrait Reference</div>
            <img src={previewModalImg} alt="Full Portrait" className="modal-full-img" />
          </div>
        </div>
      )}
    </div>
  );
}
