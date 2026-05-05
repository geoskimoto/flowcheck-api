"""Data models for API responses."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any


@dataclass
class Station:
    """Station metadata model."""
    
    station_number: str
    name: str  # API returns 'name' not 'station_name'
    agency: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    state_code: Optional[str] = None
    huc_code: Optional[str] = None
    basin_name: Optional[str] = None
    is_active: bool = True
    catchment_area: Optional[float] = None  # In sq km
    years_of_record: Optional[int] = None
    record_start_date: Optional[datetime] = None
    record_end_date: Optional[datetime] = None
    last_observation_date: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Alias for backward compatibility
    @property
    def station_name(self) -> str:
        """Alias for 'name' field."""
        return self.name
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Station':
        """Create Station from API response dictionary."""
        return cls(
            station_number=data['station_number'],
            name=data['name'],
            agency=data['agency'],
            latitude=float(data['latitude']) if data.get('latitude') else None,
            longitude=float(data['longitude']) if data.get('longitude') else None,
            state_code=data.get('state'),  # API uses 'state' not 'state_code'
            huc_code=data.get('huc_code'),
            basin_name=data.get('basin'),  # API uses 'basin' not 'basin_name'
            is_active=data.get('is_active', True),
            catchment_area=float(data['catchment_area']) if data.get('catchment_area') else None,
            years_of_record=int(data['years_of_record']) if data.get('years_of_record') else None,
            record_start_date=cls._parse_datetime(data.get('record_start_date')),
            record_end_date=cls._parse_datetime(data.get('record_end_date')),
            last_observation_date=cls._parse_datetime(data.get('last_observation_date')),
            created_at=cls._parse_datetime(data.get('created_at')),
            updated_at=cls._parse_datetime(data.get('last_updated')),  # API uses 'last_updated'
        )
    
    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        """Parse datetime string from API."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None


@dataclass
class DischargeObservation:
    """Discharge observation data model."""
    
    station_number: str
    observed_at: datetime
    discharge_value: float
    unit: str
    data_type: str
    quality_code: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DischargeObservation':
        """Create DischargeObservation from API response.
        
        API returns:
            station: int (FK)
            station_number: str (readOnly, computed from FK)
            observed_at: datetime
            discharge: decimal string (NOT 'discharge_value')
            unit: 'cfs' | 'cms'
            type: 'realtime_15min' | 'daily_mean'
            quality_code: 'P' | 'A' | ''
        """
        return cls(
            station_number=data.get('station_number', str(data.get('station', ''))),
            observed_at=datetime.fromisoformat(str(data['observed_at']).replace('Z', '+00:00')),
            discharge_value=float(data['discharge']),  # API field is 'discharge'
            unit=data.get('unit', 'cfs'),
            data_type=data.get('type', 'daily_mean'),
            quality_code=data.get('quality_code'),
        )


@dataclass
class PullConfiguration:
    """Pull configuration model."""
    
    id: int
    name: str
    data_source: str
    data_type: str
    is_enabled: bool
    station_count: int
    last_run_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PullConfiguration':
        """Create PullConfiguration from API response."""
        return cls(
            id=data['id'],
            name=data['name'],
            data_source=data['data_source'],
            data_type=data['data_type'],
            is_enabled=data['is_enabled'],
            station_count=data.get('station_count', 0),
            last_run_at=Station._parse_datetime(data.get('last_run_at')),
            created_at=Station._parse_datetime(data.get('created_at')),
        )


@dataclass
class PaginatedResponse:
    """Generic paginated response wrapper."""
    
    count: int
    next: Optional[str]
    previous: Optional[str]
    results: List[Any]
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], result_class=None) -> 'PaginatedResponse':
        """Create PaginatedResponse from API response."""
        results = data.get('results', [])
        
        if result_class and hasattr(result_class, 'from_dict'):
            results = [result_class.from_dict(item) for item in results]
        
        return cls(
            count=data.get('count', 0),
            next=data.get('next'),
            previous=data.get('previous'),
            results=results,
        )
