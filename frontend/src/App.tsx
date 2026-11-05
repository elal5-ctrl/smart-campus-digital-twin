import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent as ReactMouseEvent,
} from 'react';
import L from 'leaflet';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

type SensorKind = 'entry' | 'zone' | 'model';
type SensorStatus = 'live' | 'simulated' | 'waiting';
type Priority = 'hoch' | 'mittel' | 'niedrig';
type Lang = 'de' | 'en' | 'ja';
type Theme = 'light' | 'dark';
type Atmosphere = 'dawn' | 'morning' | 'midday' | 'afternoon' | 'evening' | 'night';
type AppView = 'campus' | 'system';
type MapMode = 'sensors' | 'forecast' | 'heatmap' | '3d';
type CampusMapMode = 'points' | 'heatmap';
type LocalizedText = Record<Lang, string>;

type SensorPoint = {
  id: string;
  name: LocalizedText;
  kind: SensorKind;
  measured: number;
  forecast: number;
  confidence: number;
  position: [number, number];
  status: SensorStatus;
};

type HeatmapPoint = {
  id: string;
  position: [number, number];
  intensity: number;
  measured: number;
  forecast: number;
  source: 'live' | 'synthetic' | 'prediction';
};

type Recommendation = {
  place: LocalizedText;
  reason: LocalizedText;
  priority: Priority;
};

type DashboardData = {
  latestTimestamp: string | null;
  sensorPoints: SensorPoint[];
  heatmapPoints?: HeatmapPoint[];
  recommendations: Recommendation[];
  measuredHours: number[];
  forecastHours: number[];
};

type WeatherReading = {
  condition: string | null;
  temperature_c: number;
  source_timestamp: string;
};

type DataMode = 'real' | 'mixed' | 'simulated';

type PublishStatus = {
  channel: string;
  topic: string;
  attempted_at: string;
  success: boolean;
  error: string | null;
  payload_source: string;
};

type ModelStatus = {
  data_mode: DataMode;
  live_sensor_count: number;
  simulated_location_count: number;
  latest_measurement: {
    sensor_id: string;
    sensor_type: string;
    zone_id: string;
    people_count: number;
    source_timestamp: string;
    received_at: string;
  } | null;
  mqtt: {
    host: string;
    port: number;
    topic_prefix: string;
    measurements_topic: string;
    thermal_image_topic: string;
    publish_weather: boolean;
    publish_people_display: boolean;
    publish_model_state: boolean;
    subscribe_measurements: boolean;
    subscribe_thermal_image: boolean;
  };
  publish_statuses: PublishStatus[];
  last_publish_error: string | null;
};

type ThermalImageStatus = {
  available: boolean;
  state: 'waiting' | 'live' | 'stale';
  received_at: string | null;
  media_type: string | null;
  size_bytes: number | null;
  revision: string | null;
  topic: string;
};

type ApiStatus = 'live' | 'fallback';

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();
const apiBaseUrl = (
  configuredApiBaseUrl || (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '')
).replace(/\/$/, '');
const dashboardEndpoint = `${apiBaseUrl}/api/v1/dashboard`;
const weatherEndpoint = `${apiBaseUrl}/api/v1/environment/weather/latest`;
const modelStatusEndpoint = `${apiBaseUrl}/api/v1/model/status`;
const thermalImageStatusEndpoint = `${apiBaseUrl}/api/v1/thermal-image/status`;
const thermalImageEndpoint = `${apiBaseUrl}/api/v1/thermal-image/latest`;

const sensorPoints: SensorPoint[] = [
  {
    id: 'K1-N',
    name: { de: 'Nordtor', en: 'North Gate', ja: '北門' },
    kind: 'entry',
    measured: 42,
    forecast: 58,
    confidence: 86,
    position: [74, 18],
    status: 'live',
  },
  {
    id: 'K1-S',
    name: { de: 'Südtor', en: 'South Gate', ja: '南門' },
    kind: 'entry',
    measured: 27,
    forecast: 35,
    confidence: 80,
    position: [14, 78],
    status: 'simulated',
  },
  {
    id: 'K2-L',
    name: { de: 'Library Plaza', en: 'Library Plaza', ja: 'ライブラリープラザ' },
    kind: 'zone',
    measured: 63,
    forecast: 71,
    confidence: 76,
    position: [56, 46],
    status: 'live',
  },
  {
    id: 'K2-C',
    name: { de: 'Central Walk', en: 'Central Walk', ja: 'セントラルウォーク' },
    kind: 'zone',
    measured: 91,
    forecast: 104,
    confidence: 72,
    position: [40, 58],
    status: 'simulated',
  },
  {
    id: 'K3-M',
    name: { de: 'Modellanzeige', en: 'Model display', ja: 'モデル表示' },
    kind: 'model',
    measured: 223,
    forecast: 268,
    confidence: 82,
    position: [25, 28],
    status: 'waiting',
  },
];

const recommendations: Recommendation[] = [
  {
    place: { de: 'Central Walk', en: 'Central Walk', ja: 'セントラルウォーク' },
    reason: {
      de: 'Hohe Auslastung mit steigender Prognose. Ein zusätzlicher Zonenpunkt erhöht die Auflösung.',
      en: 'High utilization with rising forecast. An additional zone sensor would raise the resolution.',
      ja: '利用率が高く、予測も上昇傾向です。ゾーンセンサーを追加すると解像度が上がります。',
    },
    priority: 'hoch',
  },
  {
    place: { de: 'Südtor', en: 'South Gate', ja: '南門' },
    reason: {
      de: 'Eingangszählung aktuell geschätzt. Test mit K1-Hardware priorisieren.',
      en: 'Entry count is currently estimated. Prioritize a real K1 hardware trial.',
      ja: '入口カウントは現在推定値です。K1ハードウェアでの実地テストを優先してください。',
    },
    priority: 'mittel',
  },
  {
    place: { de: 'Library Plaza', en: 'Library Plaza', ja: 'ライブラリープラザ' },
    reason: {
      de: 'Thermalpunkt liefert stabile Werte. Geeignete Referenzzone für Standortschätzungen.',
      en: 'Thermal sensor reports stable values. A solid reference zone for location estimates.',
      ja: 'サーマルセンサーは安定した値を返しています。地点推定の基準ゾーンとして使えます。',
    },
    priority: 'niedrig',
  },
];

const stackItems: ReadonlyArray<readonly [LocalizedText, string]> = [
  [{ de: 'Dashboard', en: 'Dashboard', ja: 'ダッシュボード' }, 'React, TypeScript, Vite, Leaflet'],
  [{ de: 'API', en: 'API', ja: 'API' }, 'FastAPI REST endpoints, OpenAPI docs'],
  [{ de: 'Speicher', en: 'Storage', ja: 'ストレージ' }, 'PostgreSQL via SQLModel'],
  [
    { de: 'Campusmodell', en: 'Campus model', ja: 'キャンパスモデル' },
    'Fixed locations, synthetic baseline, forecast every 15 minutes per location',
  ],
  [
    { de: 'Team B', en: 'Team B', ja: 'Team B' },
    'MQTT receive for K1/K2 status, publish weather and people-display values',
  ],
  [{ de: 'Checks', en: 'Checks', ja: 'チェック' }, 'Ruff lint, TypeScript build'],
];

const measuredHours = [34, 42, 51, 63, 78, 91, 104];
const forecastHours = [98, 86, 71, 58, 49];

const demoDashboardData: DashboardData = {
  latestTimestamp: null,
  sensorPoints,
  recommendations,
  measuredHours,
  forecastHours,
};

const copy = {
  de: {
    headerEyebrow: 'Smart Campus · Ritsumeikan Osaka',
    headerTitle: 'Campus Status',
    headerIntro: 'Systemansicht für Sensordaten, Prognosen, Datenquellen und Backend-Status.',
    viewLabel: 'Ansicht',
    campusView: 'Campus',
    systemView: 'System',
    campusHeadline: 'Wie voll ist der Campus gerade?',
    campusIntro:
      'Live-Auslastung und Kurzfristprognose für zentrale Bereiche des Ritsumeikan Osaka Ibaraki Campus.',
    campusStatusModerate: 'Der Campus ist moderat ausgelastet.',
    campusStatusBusy: 'Der Campus ist deutlich ausgelastet.',
    campusStatusCalm: 'Der Campus ist ruhig.',
    campusMapCurrent: 'Punkte',
    campusMapForecast: 'Heatmap',
    campusMapTitle: 'Campusbereich',
    campusBusiest: 'Am stärksten ausgelastet',
    campusAlternative: 'Ruhigere Alternative',
    skipLink: 'Zum Inhalt springen',
    languageLabel: 'Sprache',
    themeLabel: 'Design',
    themeLight: 'Hell',
    themeDark: 'Dunkel',
    dataSourceEyebrow: 'Datenquelle',
    statusFallbackData: 'Fallback-Daten',
    statusDisconnected: 'Verbindung prüfen',
    statusEyebrow: 'Status',
    statusLive: 'Live',
    statusLiveApi: 'Live API',
    statusSimulated: 'Geschätzt',
    statusWaiting: 'Wartet',
    sensorStatusOff: 'Aus',
    dataModeReal: 'Reale Daten',
    dataModeMixed: 'Live + geschätzt',
    dataModeSimulated: 'Simuliert',
    freshnessLabel: 'Quelle',
    integrationTitle: 'Team B Integration',
    receiveStatus: 'Empfang',
    publishStatus: 'Senden',
    mqttTopics: 'MQTT Topics',
    noLiveMeasurement: 'Keine Live-Messung',
    lastError: 'Letzter Fehler',
    okLabel: 'OK',
    failedLabel: 'Fehler',
    thermalImageTitle: 'Thermalbild',
    thermalImageAlt: 'Aktuelles Thermalbild von Team B',
    thermalImageLive: 'Live',
    thermalImageStale: 'Veraltet',
    thermalImageWaiting: 'Wartet',
    thermalImageUnavailable: 'Nicht verfügbar',
    thermalImageLastReceived: 'Zuletzt empfangen',
    thermalImageSize: 'Bildgröße',
    thermalImagePlaceholder: 'Noch kein Thermalbild empfangen',
    weatherCity: 'Osaka',
    weatherCondition: 'leicht bewölkt',
    latestMeasurement: 'Letzte Messung',
    noMeasurement: 'keine Messung',
    atmosphereDawn: 'Dämmerung',
    atmosphereMorning: 'Morgen',
    atmosphereMidday: 'Mittag',
    atmosphereAfternoon: 'Nachmittag',
    atmosphereEvening: 'Abend',
    atmosphereNight: 'Nacht',
    heroAtmosphereEyebrow: 'Atmosphäre',
    heroCurrentEyebrow: 'Aktuell auf dem Campus',
    heroForecastEyebrow: 'Prognose in 1h',
    peopleUnit: 'Personen',
    mapEyebrow: 'Campuskarte',
    mapTitle: 'Messpunkte und Zonen',
    mapAria: 'Campuskarte mit Messpunkten',
    mapModeLabel: 'Kartenmodus',
    mapModeSensors: 'Punkte',
    mapModeForecast: 'Prognose',
    mapModeHeatmap: 'Heatmap',
    mapMode3d: '3D',
    map3dAria: 'Dreidimensionale Campusansicht mit Messpunkten',
    extrapEyebrow: 'Prognosemodell',
    extrapTitle: 'Nächste Stunde',
    extrapMeasured: 'gemessen',
    extrapForecast: 'prognostiziert',
    extrapMethodPchip: 'Prognose alle 15 Minuten pro Standort',
    extrapMethodGaussian: 'Synthetische Basis aus historischen Einträgen',
    extrapMethodFourier: 'Wetterfaktor aus der aktuellen Umgebungsmessung',
    sensorsEyebrow: 'Sensordaten · Live und Sensorstatus',
    sensorsTitle: 'Sensorübersicht',
    sensorMeasured: 'Gemessen',
    sensorForecast: 'Prognose 1h',
    privacyShort: 'Aggregierte Zählungen, keine Identitäten.',
    privacyLong:
      'Sensoren liefern Personenzahlen pro Zone. Das System zeigt nur das aktuelle anonymisierte Thermalbild und speichert keinen Bildverlauf.',
    heatmapLoad: 'Auslastung',
    recoEyebrow: 'Hinweis',
    recoTitle: 'Empfehlung',
    recoPriorityHigh: 'hoch',
    recoPriorityMid: 'mittel',
    recoPriorityLow: 'niedrig',
    stackEyebrow: 'System · Kontext',
    stackTitle: 'Projektstack',
    legendEyebrow: 'Legende',
    legendCalm: 'Ruhig (<20)',
    legendBusy: 'Belebt (20–40)',
    legendCritical: 'Stark belegt (41+)',
    legendForecast: 'Prognose',
    legendHeatmap: 'Auslastung',
    navAriaLabel: 'Abschnittsnavigation',
    navOverview: 'Übersicht',
    navMap: 'Karte',
    navForecast: 'Prognose',
    navSensors: 'Sensoren',
    navRecommendations: 'Empfehlungen',
    navStack: 'Stack',
  },
  en: {
    headerEyebrow: 'Smart Campus · Ritsumeikan Osaka',
    headerTitle: 'Campus Status',
    headerIntro: 'System view for sensor data, forecasts, data sources, and backend status.',
    viewLabel: 'View',
    campusView: 'Campus',
    systemView: 'System',
    campusHeadline: 'How busy is campus right now?',
    campusIntro:
      'Live occupancy and short-term forecast for key areas of the Ritsumeikan Osaka Ibaraki Campus.',
    campusStatusModerate: 'Campus is moderately busy.',
    campusStatusBusy: 'Campus is noticeably busy.',
    campusStatusCalm: 'Campus is calm.',
    campusMapCurrent: 'Points',
    campusMapForecast: 'Heatmap',
    campusMapTitle: 'Campus Area',
    campusBusiest: 'Busiest area',
    campusAlternative: 'Quieter alternative',
    skipLink: 'Skip to content',
    languageLabel: 'Language',
    themeLabel: 'Theme',
    themeLight: 'Light',
    themeDark: 'Dark',
    dataSourceEyebrow: 'Data source',
    statusFallbackData: 'Fallback data',
    statusDisconnected: 'Check connection',
    statusEyebrow: 'Status',
    statusLive: 'Live',
    statusLiveApi: 'Live API',
    statusSimulated: 'Estimated',
    statusWaiting: 'Waiting',
    sensorStatusOff: 'Off',
    dataModeReal: 'Real data',
    dataModeMixed: 'Live + estimated',
    dataModeSimulated: 'Simulated',
    freshnessLabel: 'Source',
    integrationTitle: 'Team B Integration',
    receiveStatus: 'Receive',
    publishStatus: 'Send',
    mqttTopics: 'MQTT topics',
    noLiveMeasurement: 'No live measurement',
    lastError: 'Last error',
    okLabel: 'OK',
    failedLabel: 'Failed',
    thermalImageTitle: 'Thermal image',
    thermalImageAlt: 'Latest thermal image from Team B',
    thermalImageLive: 'Live',
    thermalImageStale: 'Stale',
    thermalImageWaiting: 'Waiting',
    thermalImageUnavailable: 'Unavailable',
    thermalImageLastReceived: 'Last received',
    thermalImageSize: 'Image size',
    thermalImagePlaceholder: 'No thermal image received yet',
    weatherCity: 'Osaka',
    weatherCondition: 'partly cloudy',
    latestMeasurement: 'Latest measurement',
    noMeasurement: 'no measurement',
    atmosphereDawn: 'Dawn',
    atmosphereMorning: 'Morning',
    atmosphereMidday: 'Midday',
    atmosphereAfternoon: 'Afternoon',
    atmosphereEvening: 'Evening',
    atmosphereNight: 'Night',
    heroAtmosphereEyebrow: 'Atmosphere',
    heroCurrentEyebrow: 'On campus right now',
    heroForecastEyebrow: 'Forecast in 1h',
    peopleUnit: 'people',
    mapEyebrow: 'Campus map',
    mapTitle: 'Sensor points and zones',
    mapAria: 'Campus map with sensor points',
    mapModeLabel: 'Map mode',
    mapModeSensors: 'Points',
    mapModeForecast: 'Forecast',
    mapModeHeatmap: 'Heatmap',
    mapMode3d: '3D',
    map3dAria: 'Three-dimensional campus view with sensor points',
    extrapEyebrow: 'Forecast model',
    extrapTitle: 'Next hour',
    extrapMeasured: 'measured',
    extrapForecast: 'forecast',
    extrapMethodPchip: 'Forecast every 15 minutes per location',
    extrapMethodGaussian: 'Synthetic baseline from historical entries',
    extrapMethodFourier: 'Weather factor from latest environment reading',
    sensorsEyebrow: 'Sensor data · live and sensor status',
    sensorsTitle: 'Sensor overview',
    sensorMeasured: 'Measured',
    sensorForecast: 'Forecast 1h',
    privacyShort: 'Aggregated counts, no identities.',
    privacyLong:
      'Sensors report counts per zone. The system shows only the latest anonymized thermal image and stores no image history.',
    heatmapLoad: 'Load',
    recoEyebrow: 'Campus advice',
    recoTitle: 'Recommendation',
    recoPriorityHigh: 'high',
    recoPriorityMid: 'medium',
    recoPriorityLow: 'low',
    stackEyebrow: 'System · Context',
    stackTitle: 'Project stack',
    legendEyebrow: 'Legend',
    legendCalm: 'Calm (<20)',
    legendBusy: 'Busy (20–40)',
    legendCritical: 'High load (41+)',
    legendForecast: 'Forecast',
    legendHeatmap: 'Load heatmap',
    navAriaLabel: 'Section navigation',
    navOverview: 'Overview',
    navMap: 'Map',
    navForecast: 'Forecast',
    navSensors: 'Sensors',
    navRecommendations: 'Recommendations',
    navStack: 'Stack',
  },
  ja: {
    headerEyebrow: 'スマートキャンパス · 立命館大阪',
    headerTitle: 'キャンパス状況',
    headerIntro: 'センサーデータ、予測、データソース、バックエンド状態のシステム表示です。',
    viewLabel: '表示',
    campusView: 'キャンパス',
    systemView: 'システム',
    campusHeadline: '現在のキャンパス混雑状況',
    campusIntro: '立命館大阪いばらきキャンパス主要エリアの混雑状況と短期予測を表示します。',
    campusStatusModerate: 'キャンパスはやや混雑しています。',
    campusStatusBusy: 'キャンパスは混雑しています。',
    campusStatusCalm: 'キャンパスは落ち着いています。',
    campusMapCurrent: 'ポイント',
    campusMapForecast: 'ヒートマップ',
    campusMapTitle: 'キャンパスエリア',
    campusBusiest: '最も混雑',
    campusAlternative: '比較的空いている場所',
    skipLink: '本文へ移動',
    languageLabel: '言語',
    themeLabel: 'テーマ',
    themeLight: 'ライト',
    themeDark: 'ダーク',
    dataSourceEyebrow: 'データソース',
    statusFallbackData: 'フォールバックデータ',
    statusDisconnected: '接続を確認',
    statusEyebrow: '状態',
    statusLive: 'ライブ',
    statusLiveApi: 'ライブAPI',
    statusSimulated: '推定',
    statusWaiting: '待機中',
    sensorStatusOff: 'オフ',
    dataModeReal: '実データ',
    dataModeMixed: 'ライブ + 推定',
    dataModeSimulated: 'シミュレーション',
    freshnessLabel: 'ソース',
    integrationTitle: 'Team B連携',
    receiveStatus: '受信',
    publishStatus: '送信',
    mqttTopics: 'MQTTトピック',
    noLiveMeasurement: 'ライブ測定なし',
    lastError: '最後のエラー',
    okLabel: 'OK',
    failedLabel: '失敗',
    thermalImageTitle: 'サーマル画像',
    thermalImageAlt: 'Team Bからの最新サーマル画像',
    thermalImageLive: 'ライブ',
    thermalImageStale: '更新停止',
    thermalImageWaiting: '待機中',
    thermalImageUnavailable: '利用不可',
    thermalImageLastReceived: '最終受信',
    thermalImageSize: '画像サイズ',
    thermalImagePlaceholder: 'サーマル画像はまだ受信されていません',
    weatherCity: '大阪',
    weatherCondition: '薄曇り',
    latestMeasurement: '最新測定',
    noMeasurement: '測定なし',
    atmosphereDawn: '夜明け',
    atmosphereMorning: '朝',
    atmosphereMidday: '昼',
    atmosphereAfternoon: '午後',
    atmosphereEvening: '夕方',
    atmosphereNight: '夜',
    heroAtmosphereEyebrow: '時間帯',
    heroCurrentEyebrow: '現在のキャンパス',
    heroForecastEyebrow: '1時間後の予測',
    peopleUnit: '人',
    mapEyebrow: 'キャンパスマップ',
    mapTitle: 'センサーポイントとゾーン',
    mapAria: 'センサーポイントを含むキャンパスマップ',
    mapModeLabel: 'マップモード',
    mapModeSensors: 'ポイント',
    mapModeForecast: '予測',
    mapModeHeatmap: 'ヒート',
    mapMode3d: '3D',
    map3dAria: 'センサーポイントを含む3Dキャンパス表示',
    extrapEyebrow: '予測モデル',
    extrapTitle: '次の1時間',
    extrapMeasured: '実測',
    extrapForecast: '予測',
    extrapMethodPchip: '各地点を15分ごとに予測',
    extrapMethodGaussian: '履歴エントリから作成した合成ベースライン',
    extrapMethodFourier: '最新の環境測定に基づく天候補正',
    sensorsEyebrow: 'センサーデータ · ライブと状態',
    sensorsTitle: 'センサー概要',
    sensorMeasured: '実測',
    sensorForecast: '1時間予測',
    privacyShort: '集約カウントのみ、個人識別なし。',
    privacyLong:
      'センサーはゾーンごとの人数を送信します。匿名化された最新のサーマル画像のみを表示し、画像履歴は保存しません。',
    heatmapLoad: '混雑度',
    recoEyebrow: 'キャンパス案内',
    recoTitle: '推奨',
    recoPriorityHigh: '高',
    recoPriorityMid: '中',
    recoPriorityLow: '低',
    stackEyebrow: 'システム · コンテキスト',
    stackTitle: 'プロジェクト構成',
    legendEyebrow: '凡例',
    legendCalm: '空き (<20)',
    legendBusy: '混雑 (20-40)',
    legendCritical: '高負荷 (41+)',
    legendForecast: '予測',
    legendHeatmap: '混雑度',
    navAriaLabel: 'セクションナビゲーション',
    navOverview: '概要',
    navMap: 'マップ',
    navForecast: '予測',
    navSensors: 'センサー',
    navRecommendations: '推奨',
    navStack: '構成',
  },
} as const;

type Dict = Record<keyof (typeof copy)['de'], string>;

function atmosphereForHour(hour: number): Atmosphere {
  if (hour < 6) return 'night';
  if (hour < 9) return 'dawn';
  if (hour < 12) return 'morning';
  if (hour < 15) return 'midday';
  if (hour < 18) return 'afternoon';
  if (hour < 21) return 'evening';
  return 'night';
}

function atmosphereLabel(atmosphere: Atmosphere, t: Dict): string {
  switch (atmosphere) {
    case 'dawn':
      return t.atmosphereDawn;
    case 'morning':
      return t.atmosphereMorning;
    case 'midday':
      return t.atmosphereMidday;
    case 'afternoon':
      return t.atmosphereAfternoon;
    case 'evening':
      return t.atmosphereEvening;
    case 'night':
      return t.atmosphereNight;
  }
}

function valueTone(value: number): 'calm' | 'busy' | 'critical' {
  if (value >= 41) return 'critical';
  if (value >= 20) return 'busy';
  return 'calm';
}

function sensorTone(point: SensorPoint): 'calm' | 'busy' | 'critical' {
  return valueTone(point.measured);
}

function colorForTone(tone: 'calm' | 'busy' | 'critical'): string {
  if (tone === 'critical') return '#a9342f';
  if (tone === 'busy') return '#c87a2d';
  return '#2d8a67';
}

function markerColor(point: SensorPoint): string {
  const sensorColor = teamBSensorColor(point.id);
  if (sensorColor) return sensorColor;
  return colorForTone(sensorTone(point));
}

function markerColorForValue(value: number): string {
  return colorForTone(valueTone(value));
}

function heatmapColorForValue(value: number): string {
  if (value >= 41) return '#a9342f';
  if (value >= 20) return '#c87a2d';
  return '#0b7f9c';
}

function sensorStatusLabel(point: SensorPoint, t: Dict): string {
  if (point.status === 'live') return t.statusLive;
  if (point.status === 'simulated') return t.statusSimulated;
  return t.sensorStatusOff;
}

function teamBSensorColor(pointId: string): string | null {
  if (pointId === 'k1-south-west-campus-entrance' || pointId.startsWith('k1')) {
    return '#1677c8';
  }
  if (pointId === 'k2-library-b-sensor-entrance' || pointId.startsWith('k2')) {
    return '#1677c8';
  }
  return null;
}

const campusModelColors: Record<string, string> = {
  buildings: '#8f9793',
  grass: '#5f8f63',
  park: '#a7c77a',
  paths: '#d8c89d',
  street: '#8e9694',
};

const campusTimeZone = 'Asia/Tokyo';

function formatTime(date: Date, lang: Lang): string {
  const localeByLang: Record<Lang, string> = {
    de: 'de-DE',
    en: 'en-GB',
    ja: 'ja-JP',
  };

  return new Intl.DateTimeFormat(localeByLang[lang], {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone: campusTimeZone,
  }).format(date);
}

function campusHour(date: Date): number {
  const hour = new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    hourCycle: 'h23',
    timeZone: campusTimeZone,
  })
    .formatToParts(date)
    .find((part) => part.type === 'hour')?.value;

  return Number(hour ?? 0);
}

function formatMeasurementTimestamp(timestamp: string | null, lang: Lang, t: Dict): string {
  if (!timestamp) return t.noMeasurement;

  const match = timestamp.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?$/);
  if (!match) return `${timestamp} JST`;

  const [, year, month, day, hour, minute] = match;
  if (lang === 'ja') return `${year}/${month}/${day} ${hour}:${minute} JST`;
  return `${day}.${month}.${year} ${hour}:${minute} JST`;
}

function formatStatusTimestamp(timestamp: string | null | undefined, lang: Lang, t: Dict): string {
  if (!timestamp) return t.noMeasurement;
  const date = new Date(/[zZ]|[+-]\d{2}:\d{2}$/.test(timestamp) ? timestamp : `${timestamp}Z`);
  if (Number.isNaN(date.getTime())) return timestamp;
  return `${new Intl.DateTimeFormat(lang === 'ja' ? 'ja-JP' : lang === 'de' ? 'de-DE' : 'en-GB', {
    dateStyle: 'short',
    timeStyle: 'short',
    timeZone: campusTimeZone,
  }).format(date)} JST`;
}

function formatByteSize(sizeBytes: number | null, lang: Lang): string {
  if (sizeBytes === null) return '-';
  const locale = lang === 'ja' ? 'ja-JP' : lang === 'de' ? 'de-DE' : 'en-GB';
  if (sizeBytes < 1_024) return `${sizeBytes} B`;
  if (sizeBytes < 1_048_576) {
    return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(sizeBytes / 1_024)} KB`;
  }
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(sizeBytes / 1_048_576)} MB`;
}

function dataModeLabel(mode: DataMode | null, t: Dict): string {
  if (mode === 'real') return t.dataModeReal;
  if (mode === 'mixed') return t.dataModeMixed;
  return t.dataModeSimulated;
}

function weatherConditionLabel(condition: string | null, lang: Lang, fallback: string): string {
  if (!condition) return fallback;

  const labels: Record<string, LocalizedText> = {
    sunny: { de: 'sonnig', en: 'sunny', ja: '晴れ' },
    cloudy: { de: 'bewölkt', en: 'cloudy', ja: '曇り' },
    fog: { de: 'neblig', en: 'fog', ja: '霧' },
    drizzle: { de: 'Nieselregen', en: 'drizzle', ja: '霧雨' },
    rain: { de: 'Regen', en: 'rain', ja: '雨' },
    snow: { de: 'Schnee', en: 'snow', ja: '雪' },
    thunderstorm: { de: 'Gewitter', en: 'thunderstorm', ja: '雷雨' },
    unknown: { de: 'unbekannt', en: 'unknown', ja: '不明' },
  };

  return labels[condition]?.[lang] ?? condition;
}

function formatWeatherSummary(weather: WeatherReading | null, lang: Lang, t: Dict): string {
  if (!weather) return `${t.weatherCondition} · 22°C`;

  const temperature = new Intl.NumberFormat(
    lang === 'ja' ? 'ja-JP' : lang === 'de' ? 'de-DE' : 'en-GB',
    {
      maximumFractionDigits: 1,
    },
  ).format(weather.temperature_c);

  return `${weatherConditionLabel(weather.condition, lang, t.weatherCondition)} · ${temperature}°C`;
}

function heatmapFromSensorPoints(points: SensorPoint[]): HeatmapPoint[] {
  const maxExpectedCount = Math.max(
    1,
    ...points.map((point) => Math.max(point.measured, point.forecast)),
  );

  return points.map((point) => ({
    id: point.id,
    position: point.position,
    intensity: Math.min(Math.max(point.measured, point.forecast) / maxExpectedCount, 1),
    measured: point.measured,
    forecast: point.forecast,
    source: point.status === 'live' ? 'live' : 'synthetic',
  }));
}

function isGeographicPosition(position: [number, number]): boolean {
  const [latitude, longitude] = position;
  return (
    latitude >= -90 && latitude <= 90 && longitude >= -180 && longitude <= 180 && longitude > 90
  );
}

function CampusMap({
  points,
  heatmapPoints,
  mode,
  t,
  theme,
  lang,
}: {
  points: SensorPoint[];
  heatmapPoints: HeatmapPoint[];
  mode: Exclude<MapMode, '3d'>;
  t: Dict;
  theme: Theme;
  lang: Lang;
}) {
  const mapRef = useRef<HTMLDivElement | null>(null);
  const instanceRef = useRef<L.Map | null>(null);

  useEffect(() => {
    if (!mapRef.current || instanceRef.current) return;

    const isRealMap = points.some((point) => isGeographicPosition(point.position));
    const campusBounds: L.LatLngBoundsExpression = [
      [34.8048, 135.5578],
      [34.8131, 135.565],
    ];
    const simpleBounds: L.LatLngBoundsExpression = [
      [0, 0],
      [90, 100],
    ];
    const map = L.map(mapRef.current, {
      crs: isRealMap ? L.CRS.EPSG3857 : L.CRS.Simple,
      minZoom: isRealMap ? 14 : 1,
      maxZoom: isRealMap ? 20 : 4,
      maxBounds: isRealMap ? campusBounds : simpleBounds,
      maxBoundsViscosity: isRealMap ? 0.65 : 1,
      zoomControl: false,
      attributionControl: isRealMap,
      keyboard: false,
    });

    mapRef.current.removeAttribute('tabindex');
    mapRef.current.classList.toggle('campus-map--real', isRealMap);

    L.control.zoom({ position: 'bottomright' }).addTo(map);

    if (isRealMap) {
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 20,
        attribution: '&copy; OpenStreetMap contributors',
      }).addTo(map);

      const pointBounds = L.latLngBounds(points.map((point) => point.position));
      if (pointBounds.isValid()) {
        map.fitBounds(pointBounds.pad(0.06), { maxZoom: 18 });
      } else {
        map.setView([34.81025, 135.56145], 17);
      }
    } else {
      map.fitBounds(simpleBounds);

      const campusShape: L.LatLngExpression[] = [
        [9, 15],
        [12, 30],
        [10, 47],
        [18, 70],
        [35, 88],
        [58, 91],
        [78, 82],
        [84, 63],
        [82, 30],
        [72, 14],
        [44, 9],
        [18, 10],
      ];

      L.polygon(campusShape, {
        color: theme === 'dark' ? '#3a4a44' : '#6f7d75',
        weight: 2,
        fillColor: theme === 'dark' ? '#1c211f' : '#edf1ed',
        fillOpacity: 0.92,
      }).addTo(map);

      L.polyline(
        [
          [24, 39],
          [37, 47],
          [51, 58],
          [65, 73],
        ],
        { color: '#65756f', weight: 5, opacity: 0.2, dashArray: '10 9' },
      ).addTo(map);
    }

    if (mode === 'heatmap') {
      heatmapPoints.forEach((point) => {
        const heatmapValue = Math.max(point.measured, point.forecast);
        const normalizedLoad = Math.max(point.intensity, Math.min(heatmapValue / 41, 1));
        const color = heatmapColorForValue(heatmapValue);
        const coverageRadius = isRealMap
          ? 14 + Math.round(normalizedLoad * 30)
          : 10 + Math.round(normalizedLoad * 18);
        const coreRadius = isRealMap
          ? Math.max(5, Math.round(coverageRadius * 0.24))
          : Math.max(4, Math.round(coverageRadius * 0.28));
        const marker = isRealMap
          ? L.circle(point.position, {
              radius: coverageRadius,
              color,
              fillColor: color,
              fillOpacity: 0.08 + normalizedLoad * 0.12,
              opacity: 0.18 + normalizedLoad * 0.2,
              weight: 0,
              className: 'campus-map__heat-area',
            })
          : L.circleMarker(point.position, {
              radius: coverageRadius,
              color,
              fillColor: color,
              fillOpacity: 0.08 + normalizedLoad * 0.12,
              opacity: 0.18 + normalizedLoad * 0.2,
              weight: 0,
              className: 'campus-map__heat-area',
            });

        marker.addTo(map);

        const core = isRealMap
          ? L.circle(point.position, {
              radius: coreRadius,
              color,
              fillColor: color,
              fillOpacity: 0.22 + normalizedLoad * 0.2,
              opacity: 0.28 + normalizedLoad * 0.28,
              weight: 0,
              interactive: true,
              className: 'campus-map__heat-core',
            })
          : L.circleMarker(point.position, {
              radius: coreRadius,
              color,
              fillColor: color,
              fillOpacity: 0.22 + normalizedLoad * 0.2,
              opacity: 0.28 + normalizedLoad * 0.28,
              weight: 0,
              interactive: true,
              className: 'campus-map__heat-core',
            });
        core.addTo(map);

        L.circleMarker(point.position, {
          radius: isRealMap ? 3.5 : 3,
          color,
          fillColor: color,
          fillOpacity: 0.95,
          opacity: 0.95,
          weight: 0,
          interactive: false,
          className: 'campus-map__heat-dot',
        }).addTo(map);

        if (heatmapValue >= 41) {
          L.tooltip({
            permanent: true,
            direction: 'top',
            offset: [0, -12],
            className: 'campus-map__heat-label',
          })
            .setLatLng(point.position)
            .setContent(String(heatmapValue))
            .addTo(map);
        }

        const pointName =
          points.find((sensorPoint) => sensorPoint.id === point.id)?.name[lang] ?? point.id;

        marker.bindTooltip(pointName, {
          direction: 'right',
          offset: [10, 0],
          className: 'campus-map__tooltip',
        });

        marker.bindPopup(
          `<strong>${pointName}</strong><br>${t.heatmapLoad}: ${heatmapValue} ${t.peopleUnit}<br>${t.sensorMeasured}: ${point.measured} ${t.peopleUnit}<br>${t.sensorForecast}: ${point.forecast}`,
        );
      });
    }

    points.forEach((point) => {
      if (mode === 'heatmap') return;

      const value = mode === 'forecast' ? point.forecast : point.measured;
      const color =
        teamBSensorColor(point.id) ??
        (mode === 'forecast' ? markerColorForValue(value) : markerColor(point));
      const radius = isRealMap ? 12 : point.kind === 'model' ? 12 : 10;
      if (isRealMap) {
        L.circleMarker(point.position, {
          radius: radius + 6,
          color: theme === 'dark' ? '#f6fff8' : '#10231d',
          fillColor: theme === 'dark' ? '#f6fff8' : '#10231d',
          fillOpacity: theme === 'dark' ? 0.22 : 0.16,
          opacity: theme === 'dark' ? 0.72 : 0.42,
          weight: 2,
          interactive: false,
          className: 'campus-map__marker-halo',
        }).addTo(map);
      }
      const marker = L.circleMarker(point.position, {
        radius,
        color: isRealMap ? '#f8fff9' : color,
        fillColor: color,
        fillOpacity: 0.94,
        weight: isRealMap ? 3.2 : 3,
        className: 'campus-map__marker',
      }).addTo(map);

      const pointName = point.name[lang];

      marker.bindTooltip(pointName, {
        direction: 'right',
        offset: [10, 0],
        className: 'campus-map__tooltip',
      });

      marker.bindPopup(
        `<strong>${pointName}</strong><br>${t.sensorMeasured}: ${point.measured} ${t.peopleUnit}<br>${t.sensorForecast}: ${point.forecast}<br>${t.statusEyebrow}: ${sensorStatusLabel(point, t)}`,
      );
    });

    instanceRef.current = map;

    return () => {
      map.remove();
      instanceRef.current = null;
    };
  }, [points, heatmapPoints, mode, t, theme, lang]);

  return <div className="campus-map" ref={mapRef} role="img" aria-label={t.mapAria} />;
}

function CampusScene({ t, theme }: { t: Dict; theme: Theme }) {
  const sceneRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const host = sceneRef.current;
    if (!host) return;

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(theme === 'dark' ? 0x15211d : 0xe8eee9, 22, 58);

    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 120);
    camera.position.set(9.6, 9.2, 13.8);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      preserveDrawingBuffer: true,
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setClearColor(0x000000, 0);
    host.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enablePan = true;
    controls.panSpeed = 0.45;
    controls.enableZoom = true;
    controls.zoomSpeed = 0.75;
    controls.minDistance = 8;
    controls.maxDistance = 28;
    controls.maxPolarAngle = Math.PI * 0.48;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.45;
    controls.target.set(0, 0.8, 0);
    controls.update();

    let idleTimer = 0;
    let isLeftPointerDown = false;
    const markUserInteraction = () => {
      controls.autoRotate = false;
      window.clearTimeout(idleTimer);
      idleTimer = window.setTimeout(() => {
        controls.autoRotate = true;
      }, 2400);
    };

    const zoomWhileDragging = (event: WheelEvent) => {
      markUserInteraction();
      if (!isLeftPointerDown) return;

      event.preventDefault();

      const targetToCamera = camera.position.clone().sub(controls.target);
      const currentDistance = targetToCamera.length();
      const zoomFactor = event.deltaY > 0 ? 1.12 : 0.88;
      const nextDistance = THREE.MathUtils.clamp(
        currentDistance * zoomFactor,
        controls.minDistance,
        controls.maxDistance,
      );

      camera.position.copy(controls.target).add(targetToCamera.setLength(nextDistance));
      camera.updateProjectionMatrix();
      controls.update();
    };

    const handlePointerDown = (event: PointerEvent) => {
      if (event.button !== 0) return;
      isLeftPointerDown = true;
      markUserInteraction();
    };

    const handlePointerUp = () => {
      isLeftPointerDown = false;
    };

    controls.addEventListener('start', markUserInteraction);
    renderer.domElement.addEventListener('pointerdown', handlePointerDown);
    window.addEventListener('pointerup', handlePointerUp);
    window.addEventListener('pointercancel', handlePointerUp);
    renderer.domElement.addEventListener('wheel', zoomWhileDragging, { passive: false });

    scene.add(new THREE.HemisphereLight(0xf4fff8, theme === 'dark' ? 0x10251d : 0xa8b8ae, 2.2));

    const sun = new THREE.DirectionalLight(0xfff3d3, 2.4);
    sun.position.set(8, 14, 10);
    scene.add(sun);

    const campusGroup = new THREE.Group();
    scene.add(campusGroup);

    const addFallbackBase = () => {
      const ground = new THREE.Mesh(
        new THREE.BoxGeometry(22, 0.28, 17),
        new THREE.MeshStandardMaterial({
          color: theme === 'dark' ? 0x1d2c27 : 0xe2e9e3,
          roughness: 0.88,
          metalness: 0.02,
        }),
      );
      ground.position.y = -0.14;
      campusGroup.add(ground);
    };

    let modelRoot: THREE.Object3D | null = null;
    let isDisposed = false;

    new GLTFLoader().load(
      '/campusmodel.glb',
      (gltf) => {
        if (isDisposed) return;

        modelRoot = gltf.scene;
        const box = new THREE.Box3().setFromObject(modelRoot);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        const largestSide = Math.max(size.x, size.y, size.z, 1);
        const scale = 22 / largestSide;

        modelRoot.position.sub(center);
        modelRoot.position.x -= 0.17;
        modelRoot.scale.setScalar(scale);
        modelRoot.rotation.y = Math.PI;

        const scaledBox = new THREE.Box3().setFromObject(modelRoot);
        modelRoot.position.y -= scaledBox.min.y;

        modelRoot.traverse((object) => {
          if (!(object instanceof THREE.Mesh)) return;
          object.castShadow = false;
          object.receiveShadow = true;
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.forEach((material) => {
            const objectKey = object.name.trim().toLowerCase();
            const materialKey = material.name.trim().toLowerCase();
            const color = campusModelColors[objectKey] ?? campusModelColors[materialKey];

            if (color && 'color' in material && material.color instanceof THREE.Color) {
              material.color.set(color);
            }

            if ('roughness' in material)
              material.roughness = Math.max(material.roughness ?? 0.6, 0.55);
          });
        });

        campusGroup.add(modelRoot);

        const fittedBox = new THREE.Box3().setFromObject(modelRoot);
        const fittedCenter = fittedBox.getCenter(new THREE.Vector3());
        controls.target.set(0, Math.max(0, fittedCenter.y * 0.08), fittedCenter.z);
        controls.update();
      },
      undefined,
      () => {
        if (!isDisposed) addFallbackBase();
      },
    );

    const resize = () => {
      const rect = host.getBoundingClientRect();
      const width = Math.max(1, rect.width);
      const height = Math.max(1, rect.height);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
    };

    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(host);
    resize();

    let frame = 0;
    const animate = () => {
      frame = window.requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };

    animate();

    return () => {
      isDisposed = true;
      window.cancelAnimationFrame(frame);
      window.clearTimeout(idleTimer);
      controls.removeEventListener('start', markUserInteraction);
      renderer.domElement.removeEventListener('pointerdown', handlePointerDown);
      window.removeEventListener('pointerup', handlePointerUp);
      window.removeEventListener('pointercancel', handlePointerUp);
      renderer.domElement.removeEventListener('wheel', zoomWhileDragging);
      controls.dispose();
      resizeObserver.disconnect();
      renderer.dispose();
      scene.traverse((object) => {
        if (!(object instanceof THREE.Mesh)) return;
        object.geometry.dispose();
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        materials.forEach((material) => material.dispose());
      });
      modelRoot = null;
      renderer.domElement.remove();
    };
  }, [theme]);

  return (
    <div className="campus-map campus-map--3d" ref={sceneRef} role="img" aria-label={t.map3dAria} />
  );
}

function MapModeSwitch({
  mode,
  onChange,
  t,
}: {
  mode: MapMode;
  onChange: (mode: MapMode) => void;
  t: Dict;
}) {
  return (
    <div className="map-mode-toggle" role="group" aria-label={t.mapModeLabel} data-mode={mode}>
      <button
        type="button"
        className="map-mode-toggle__option"
        aria-pressed={mode === 'sensors'}
        onClick={() => onChange('sensors')}
      >
        {t.mapModeSensors}
      </button>
      <button
        type="button"
        className="map-mode-toggle__option"
        aria-pressed={mode === 'heatmap'}
        onClick={() => onChange('heatmap')}
      >
        {t.mapModeHeatmap}
      </button>
      <button
        type="button"
        className="map-mode-toggle__option"
        aria-pressed={mode === '3d'}
        onClick={() => onChange('3d')}
      >
        {t.mapMode3d}
      </button>
    </div>
  );
}

function ViewSwitch({
  view,
  onChange,
  t,
}: {
  view: AppView;
  onChange: (view: AppView) => void;
  t: Dict;
}) {
  return (
    <div className="view-toggle" role="group" aria-label={t.viewLabel} data-view={view}>
      <button
        type="button"
        className="view-toggle__option"
        aria-pressed={view === 'campus'}
        onClick={() => onChange('campus')}
      >
        {t.campusView}
      </button>
      <button
        type="button"
        className="view-toggle__option"
        aria-pressed={view === 'system'}
        onClick={() => onChange('system')}
      >
        {t.systemView}
      </button>
    </div>
  );
}

function CampusModeSwitch({
  mode,
  onChange,
  t,
}: {
  mode: CampusMapMode;
  onChange: (mode: CampusMapMode) => void;
  t: Dict;
}) {
  return (
    <div className="campus-mode-toggle" role="group" aria-label={t.mapModeLabel} data-mode={mode}>
      <button
        type="button"
        className="campus-mode-toggle__option"
        aria-pressed={mode === 'points'}
        onClick={() => onChange('points')}
      >
        {t.campusMapCurrent}
      </button>
      <button
        type="button"
        className="campus-mode-toggle__option"
        aria-pressed={mode === 'heatmap'}
        onClick={() => onChange('heatmap')}
      >
        {t.campusMapForecast}
      </button>
    </div>
  );
}

function Sparkline({ measured, forecast, t }: { measured: number[]; forecast: number[]; t: Dict }) {
  const all = useMemo(() => [...measured, ...forecast], [measured, forecast]);
  const max = Math.max(...all);
  const min = Math.min(...all);
  const total = all.length;

  const point = (value: number, index: number) => {
    const x = (index / (total - 1)) * 100;
    const y = 100 - ((value - min) / Math.max(1, max - min)) * 70 - 14;
    return { x, y };
  };

  const measuredPath = measured.map((v, i) => point(v, i));
  const lastMeasured = measuredPath[measuredPath.length - 1];
  const forecastPath = forecast.map((v, i) => point(v, measured.length - 1 + i + 1));
  const forecastWithAnchor = [lastMeasured, ...forecastPath];

  const measuredStr = measuredPath.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');
  const forecastStr = forecastWithAnchor
    .map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`)
    .join(' ');

  const forecastStartX = lastMeasured.x;

  return (
    <svg
      className="sparkline"
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      role="img"
      aria-label={`${t.extrapTitle}: ${t.extrapMeasured} + ${t.extrapForecast}`}
    >
      <defs>
        <pattern
          id="forecast-hatch"
          width="6"
          height="6"
          patternTransform="rotate(45)"
          patternUnits="userSpaceOnUse"
        >
          <line x1="0" y1="0" x2="0" y2="6" className="sparkline__hatch" />
        </pattern>
      </defs>
      <rect
        x={forecastStartX}
        y="0"
        width={100 - forecastStartX}
        height="100"
        fill="url(#forecast-hatch)"
        className="sparkline__forecast-band"
      />
      <polyline points={measuredStr} className="sparkline__measured" />
      <polyline points={forecastStr} className="sparkline__forecast" />
      <line x1={forecastStartX} y1="6" x2={forecastStartX} y2="94" className="sparkline__divider" />
    </svg>
  );
}

function SensorCard({ point, t, lang }: { point: SensorPoint; t: Dict; lang: Lang }) {
  const tone = sensorTone(point);
  const pointName = point.name[lang];
  const statusLabel = sensorStatusLabel(point, t);

  return (
    <article className={`sensor-card sensor-card--${tone}`} aria-label={`${point.id} ${pointName}`}>
      <header className="sensor-card__head">
        <p className="sensor-card__id">{point.id}</p>
        <h3 className="sensor-card__name">{pointName}</h3>
      </header>

      <div className="sensor-card__row sensor-card__row--measured">
        <span className="sensor-card__row-label">{t.sensorMeasured}</span>
        <strong className="sensor-card__row-metric">{point.measured}</strong>
      </div>

      <div className="sensor-card__row sensor-card__row--forecast">
        <span className="sensor-card__row-label">{t.sensorForecast}</span>
        <strong className="sensor-card__row-metric">{point.forecast}</strong>
      </div>

      <footer className="sensor-card__foot">
        <span className={`sensor-card__status sensor-card__status--${point.status}`}>
          {statusLabel}
        </span>
      </footer>
    </article>
  );
}

function SensorOverview({
  sensorPoints,
  t,
  lang,
  showPrivacy = true,
}: {
  sensorPoints: SensorPoint[];
  t: Dict;
  lang: Lang;
  showPrivacy?: boolean;
}) {
  return (
    <section className="sensor-section" id="sensors">
      <div className="section-heading">
        <div>
          <p className="eyebrow">{t.sensorsEyebrow}</p>
          <h2>{t.sensorsTitle}</h2>
        </div>
      </div>
      <div className="sensor-grid">
        {sensorPoints.map((point) => (
          <SensorCard key={point.id} point={point} t={t} lang={lang} />
        ))}
      </div>
      {showPrivacy ? (
        <p className="privacy-ribbon" role="note">
          <strong>{t.privacyShort}</strong> {t.privacyLong}
        </p>
      ) : null}
    </section>
  );
}

function Legend({ t }: { t: Dict }) {
  return (
    <div className="legend" aria-label={t.legendEyebrow}>
      <p className="eyebrow">{t.legendEyebrow}</p>
      <ul className="legend__group legend__group--load">
        <li>
          <span className="legend__dot legend__dot--calm" aria-hidden="true" />
          {t.legendCalm}
        </li>
        <li>
          <span className="legend__dot legend__dot--busy" aria-hidden="true" />
          {t.legendBusy}
        </li>
        <li>
          <span className="legend__dot legend__dot--critical" aria-hidden="true" />
          {t.legendCritical}
        </li>
      </ul>
      <ul className="legend__group legend__group--overlay">
        <li>
          <span className="legend__dot legend__dot--forecast" aria-hidden="true" />
          {t.legendForecast}
        </li>
        <li>
          <span className="legend__dot legend__dot--heatmap" aria-hidden="true" />
          {t.legendHeatmap}
        </li>
      </ul>
    </div>
  );
}

function TeamBIntegrationPanel({
  status,
  t,
  lang,
}: {
  status: ModelStatus | null;
  t: Dict;
  lang: Lang;
}) {
  const publishStatuses = status?.publish_statuses ?? [];
  const [thermalStatus, setThermalStatus] = useState<ThermalImageStatus | null>(null);
  const [thermalImageUrl, setThermalImageUrl] = useState<string | null>(null);
  const [thermalUnavailable, setThermalUnavailable] = useState(false);

  useEffect(() => {
    let disposed = false;
    let activeController: AbortController | null = null;

    async function loadThermalStatus() {
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      try {
        const response = await fetch(thermalImageStatusEndpoint, {
          headers: { Accept: 'application/json' },
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`Thermal image status API returned ${response.status}`);
        }

        const nextStatus = (await response.json()) as ThermalImageStatus;
        if (disposed) return;
        setThermalStatus(nextStatus);
        setThermalUnavailable(false);
        if (nextStatus.available && nextStatus.revision) {
          setThermalImageUrl(
            `${thermalImageEndpoint}?revision=${encodeURIComponent(nextStatus.revision)}`,
          );
        }
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        if (!disposed) setThermalUnavailable(true);
      }
    }

    void loadThermalStatus();
    const id = window.setInterval(() => void loadThermalStatus(), 2_000);
    return () => {
      disposed = true;
      activeController?.abort();
      window.clearInterval(id);
    };
  }, []);

  const thermalState = thermalUnavailable ? 'unavailable' : (thermalStatus?.state ?? 'waiting');
  const thermalStateLabel =
    thermalState === 'live'
      ? t.thermalImageLive
      : thermalState === 'stale'
        ? t.thermalImageStale
        : thermalState === 'unavailable'
          ? t.thermalImageUnavailable
          : t.thermalImageWaiting;

  return (
    <div className="integration-panel" id="integration">
      <div className="section-heading compact">
        <div>
          <p className="eyebrow">{t.stackEyebrow}</p>
          <h2>{t.integrationTitle}</h2>
        </div>
        <span className={`integration-mode integration-mode--${status?.data_mode ?? 'simulated'}`}>
          {dataModeLabel(status?.data_mode ?? null, t)}
        </span>
      </div>

      <dl className="integration-summary">
        <div>
          <dt>{t.receiveStatus}</dt>
          <dd>
            {status?.latest_measurement
              ? `${status.latest_measurement.sensor_id} · ${status.latest_measurement.people_count}`
              : t.noLiveMeasurement}
          </dd>
        </div>
        <div>
          <dt>{t.latestMeasurement}</dt>
          <dd>{formatStatusTimestamp(status?.latest_measurement?.received_at, lang, t)}</dd>
        </div>
        <div>
          <dt>{t.mqttTopics}</dt>
          <dd>
            {status ? `${status.mqtt.topic_prefix} · ${status.mqtt.measurements_topic}` : '-'}
          </dd>
        </div>
        <div>
          <dt>{t.lastError}</dt>
          <dd>{status?.last_publish_error ?? '-'}</dd>
        </div>
      </dl>

      <div className="publish-list" aria-label={t.publishStatus}>
        {publishStatuses.length > 0 ? (
          publishStatuses.map((item) => (
            <article className="publish-item" key={item.channel}>
              <span className={`publish-item__dot ${item.success ? 'is-ok' : 'is-failed'}`} />
              <div>
                <h3>{item.channel}</h3>
                <p>{item.topic}</p>
              </div>
              <strong>{item.success ? t.okLabel : t.failedLabel}</strong>
            </article>
          ))
        ) : (
          <article className="publish-item">
            <span className="publish-item__dot is-failed" />
            <div>
              <h3>{t.publishStatus}</h3>
              <p>{t.noMeasurement}</p>
            </div>
            <strong>{t.statusWaiting}</strong>
          </article>
        )}
      </div>

      <section className="thermal-feed" aria-labelledby="thermal-feed-title">
        <div className="thermal-feed__heading">
          <h3 id="thermal-feed-title">{t.thermalImageTitle}</h3>
          <span className={`thermal-feed__state thermal-feed__state--${thermalState}`}>
            {thermalStateLabel}
          </span>
        </div>
        <div className="thermal-feed__frame">
          {thermalImageUrl ? (
            <img
              src={thermalImageUrl}
              alt={t.thermalImageAlt}
              onError={() => setThermalUnavailable(true)}
            />
          ) : (
            <p>{t.thermalImagePlaceholder}</p>
          )}
        </div>
        <dl className="thermal-feed__meta">
          <div>
            <dt>{t.thermalImageLastReceived}</dt>
            <dd>{formatStatusTimestamp(thermalStatus?.received_at, lang, t)}</dd>
          </div>
          <div>
            <dt>{t.thermalImageSize}</dt>
            <dd>{formatByteSize(thermalStatus?.size_bytes ?? null, lang)}</dd>
          </div>
          <div>
            <dt>{t.mqttTopics}</dt>
            <dd>{thermalStatus?.topic ?? status?.mqtt.thermal_image_topic ?? '-'}</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}

type SectionItem = { id: string; label: string };

function SectionNav({
  items,
  ariaLabel,
}: {
  items: ReadonlyArray<SectionItem>;
  ariaLabel: string;
}) {
  const [active, setActive] = useState(items[0]?.id ?? '');
  const [progress, setProgress] = useState(0);
  // While true, a click is steering the highlight and scroll detection must not
  // override it. Released as soon as the user scrolls under their own input.
  const lockedRef = useRef(false);

  useEffect(() => {
    if (items.length === 0) return;
    const ids = items.map((item) => item.id);

    // Scroll-position driven so the last (short, bottom-anchored) section
    // reliably becomes active once the page is scrolled all the way down —
    // an IntersectionObserver band can never be reached by a short final
    // section, which left the bottom item permanently un-highlighted.
    const update = () => {
      const scrollY = window.scrollY;
      const viewport = window.innerHeight;
      const docHeight = document.documentElement.scrollHeight;
      const scrollable = Math.max(1, docHeight - viewport);

      setProgress(Math.min(1, Math.max(0, scrollY / scrollable)));

      // A click owns the highlight until the user scrolls themselves; otherwise
      // clicking a section near the page bottom (which can't scroll all the way
      // to the top) would let the bottom-snap below steal the highlight.
      if (lockedRef.current) return;

      // Snap to the first item at the very top — the leading section's top can
      // sit below the reading line on load, which otherwise left it unselected.
      if (scrollY <= 2) {
        setActive(ids[0]);
        return;
      }

      // Snap to the final item once we've effectively hit the bottom.
      if (scrollY + viewport >= docHeight - 2) {
        setActive(ids[ids.length - 1]);
        return;
      }

      // Otherwise the active section is the last one whose top has crossed
      // a reading line ~35% down the viewport.
      const line = viewport * 0.35;
      let current = ids[0];
      for (const id of ids) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= line) current = id;
      }
      setActive(current);
    };

    // Any genuine user scroll input hands control back to scroll detection.
    const release = () => {
      if (!lockedRef.current) return;
      lockedRef.current = false;
      update();
    };

    update();
    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    window.addEventListener('wheel', release, { passive: true });
    window.addEventListener('touchmove', release, { passive: true });
    window.addEventListener('keydown', release);
    return () => {
      window.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
      window.removeEventListener('wheel', release);
      window.removeEventListener('touchmove', release);
      window.removeEventListener('keydown', release);
    };
  }, [items]);

  const handleClick = (event: ReactMouseEvent<HTMLAnchorElement>, id: string, isFirst: boolean) => {
    event.preventDefault();

    // The clicked item wins the highlight immediately and holds it until the
    // user scrolls — so e.g. "Sensoren" stays selected.
    lockedRef.current = true;
    setActive(id);

    const behavior: ScrollBehavior = prefersReducedMotion() ? 'auto' : 'smooth';

    if (isFirst) {
      // The first section sits below the header, so go to the very top.
      window.scrollTo({ top: 0, behavior });
      return;
    }

    const el = document.getElementById(id);
    if (!el) return;

    // Land the section a little below the top (upper-middle) rather than
    // top-aligned, and clamp to the scrollable range so it doesn't jam against
    // the page bottom.
    const viewport = window.innerHeight;
    const offset = Math.min(viewport * 0.22, 200);
    const maxScroll = document.documentElement.scrollHeight - viewport;
    const target = el.getBoundingClientRect().top + window.scrollY - offset;
    window.scrollTo({ top: Math.max(0, Math.min(target, maxScroll)), behavior });
  };

  return (
    <nav
      className="section-nav"
      aria-label={ariaLabel}
      style={{ '--scroll-progress': progress } as CSSProperties}
    >
      <ul>
        {items.map((item, index) => (
          <li key={item.id}>
            <a
              href={`#${item.id}`}
              className="section-nav__link"
              aria-current={active === item.id ? 'true' : undefined}
              onClick={(event) => handleClick(event, item.id, index === 0)}
            >
              <span className="section-nav__dot" aria-hidden="true" />
              <span className="section-nav__label">{item.label}</span>
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined') return false;
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

function readInitialTheme(): Theme {
  if (typeof window === 'undefined') return 'light';
  const stored = window.localStorage.getItem('theme');
  if (stored === 'light' || stored === 'dark') return stored;
  return 'light';
}

function readInitialLang(): Lang {
  if (typeof window === 'undefined') return 'en';
  const stored = window.localStorage.getItem('lang');
  if (stored === 'de' || stored === 'en' || stored === 'ja') return stored;
  return 'en';
}

function readInitialAppView(): AppView {
  if (typeof window === 'undefined') return 'campus';
  const stored = window.localStorage.getItem('appView');
  if (stored === 'campus' || stored === 'system') return stored;
  return 'campus';
}

function readInitialCampusMapMode(): CampusMapMode {
  if (typeof window === 'undefined') return 'points';
  const stored = window.localStorage.getItem('campusMapMode');
  if (stored === 'points' || stored === 'forecast') return 'points';
  if (stored === 'heatmap' || stored === 'current') return 'heatmap';
  return 'points';
}

function readInitialMapMode(): MapMode {
  if (typeof window === 'undefined') return 'sensors';
  const stored = window.localStorage.getItem('mapMode');
  if (stored === 'sensors' || stored === 'heatmap' || stored === '3d') {
    return stored;
  }
  return 'sensors';
}

export function App() {
  const [lang, setLang] = useState<Lang>(readInitialLang);
  const t = copy[lang];
  const [dashboardData, setDashboardData] = useState<DashboardData>(demoDashboardData);
  const [weather, setWeather] = useState<WeatherReading | null>(null);
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [apiStatus, setApiStatus] = useState<ApiStatus>('fallback');
  const [appView, setAppView] = useState<AppView>(readInitialAppView);
  const [campusMapMode, setCampusMapMode] = useState<CampusMapMode>(readInitialCampusMapMode);
  const [mapMode, setMapMode] = useState<MapMode>(readInitialMapMode);
  const {
    latestTimestamp,
    sensorPoints,
    heatmapPoints: apiHeatmapPoints,
    recommendations,
    measuredHours,
    forecastHours,
  } = dashboardData;
  const heatmapPoints = useMemo(
    () =>
      apiHeatmapPoints && apiHeatmapPoints.length > 0
        ? apiHeatmapPoints
        : heatmapFromSensorPoints(sensorPoints),
    [apiHeatmapPoints, sensorPoints],
  );

  const [theme, setTheme] = useState<Theme>(readInitialTheme);
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    window.localStorage.setItem('theme', theme);
  }, [theme]);

  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(id);
  }, []);

  const atmosphere = atmosphereForHour(campusHour(now));
  const forecastTarget = new Date(now.getTime() + 60 * 60 * 1000);
  const dataSourceEyebrow = appView === 'campus' ? t.statusEyebrow : t.dataSourceEyebrow;
  const dataSourceLabel = modelStatus?.data_mode
    ? dataModeLabel(modelStatus.data_mode, t)
    : apiStatus === 'live'
      ? appView === 'campus'
        ? t.statusLive
        : t.statusLiveApi
      : appView === 'campus'
        ? t.statusDisconnected
        : t.statusFallbackData;

  useEffect(() => {
    const controller = new AbortController();

    async function loadDashboardData() {
      try {
        const response = await fetch(dashboardEndpoint, {
          headers: { Accept: 'application/json' },
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`Dashboard API returned ${response.status}`);
        }

        const data = (await response.json()) as DashboardData;
        setDashboardData(data);
        setApiStatus('live');
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setDashboardData(demoDashboardData);
        setApiStatus('fallback');
      }
    }

    void loadDashboardData();

    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();

    async function loadModelStatus() {
      try {
        const response = await fetch(modelStatusEndpoint, {
          headers: { Accept: 'application/json' },
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`Model status API returned ${response.status}`);
        }

        const data = (await response.json()) as ModelStatus;
        setModelStatus(data);
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setModelStatus(null);
      }
    }

    void loadModelStatus();
    const id = window.setInterval(() => void loadModelStatus(), 30_000);

    return () => {
      controller.abort();
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();

    async function loadWeather() {
      try {
        const response = await fetch(weatherEndpoint, {
          headers: { Accept: 'application/json' },
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`Weather API returned ${response.status}`);
        }

        const data = (await response.json()) as WeatherReading | null;
        setWeather(data);
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setWeather(null);
      }
    }

    void loadWeather();

    return () => controller.abort();
  }, []);

  const totals = useMemo(() => {
    const current = sensorPoints.reduce((sum, point) => sum + point.measured, 0);
    const forecast = sensorPoints.reduce((sum, point) => sum + point.forecast, 0);
    return { current, forecast };
  }, [sensorPoints]);
  const campusSummary = useMemo(() => {
    const sortedByMeasured = [...sensorPoints].sort((a, b) => b.measured - a.measured);
    const sortedByQuiet = [...sensorPoints].sort((a, b) => a.measured - b.measured);
    const busiest = sortedByMeasured[0] ?? null;
    const quietest = sortedByQuiet[0] ?? null;
    const status =
      totals.current >= 300
        ? t.campusStatusBusy
        : totals.current >= 140
          ? t.campusStatusModerate
          : t.campusStatusCalm;
    return { busiest, quietest, status };
  }, [sensorPoints, t, totals]);

  useEffect(() => {
    document.documentElement.lang = lang;
    window.localStorage.setItem('lang', lang);
  }, [lang]);

  useEffect(() => {
    window.localStorage.setItem('appView', appView);
  }, [appView]);

  useEffect(() => {
    window.localStorage.setItem('campusMapMode', campusMapMode);
  }, [campusMapMode]);

  useEffect(() => {
    window.localStorage.setItem('mapMode', mapMode);
  }, [mapMode]);

  const navItems = useMemo<ReadonlyArray<SectionItem>>(
    () =>
      appView === 'campus'
        ? [
            { id: 'dashboard', label: t.navOverview },
            { id: 'map', label: t.navMap },
            { id: 'sensors', label: t.navSensors },
            { id: 'recommendations', label: t.navRecommendations },
          ]
        : [
            { id: 'dashboard', label: t.navOverview },
            { id: 'map', label: t.navMap },
            { id: 'integration', label: t.integrationTitle },
            { id: 'sensors', label: t.navSensors },
            { id: 'recommendations', label: t.navRecommendations },
          ],
    [appView, t],
  );

  return (
    <main className={`app app--${atmosphere} app--${appView}`}>
      <a className="skip-link" href="#dashboard">
        {t.skipLink}
      </a>

      <SectionNav items={navItems} ariaLabel={t.navAriaLabel} />

      <header className="app-header" aria-labelledby="app-title">
        <div className="app-header__identity">
          <div className="partner-lockup" aria-label="TU Berlin and Ritsumeikan University">
            <img src="/Ritsumeikan_University_logo.svg" alt="Ritsumeikan University" />
            <span aria-hidden="true" />
            <img src="/TU-Berlin-Logo.svg" alt="Technische Universität Berlin" />
          </div>
          <p className="eyebrow">{t.headerEyebrow}</p>
          <h1 id="app-title" className="app-header__title">
            {appView === 'campus' ? 'Ritsumeikan Campus Status' : t.headerTitle}
          </h1>
          <p className="app-header__intro">
            {appView === 'campus' ? t.campusIntro : t.headerIntro}
          </p>
        </div>

        <div className="app-header__meta">
          <div className="app-header__toggles">
            <ViewSwitch view={appView} onChange={setAppView} t={t} />
            <div className="lang-toggle" role="group" aria-label={t.languageLabel} data-lang={lang}>
              <button
                type="button"
                className="lang-toggle__option"
                aria-pressed={lang === 'de'}
                onClick={() => setLang('de')}
              >
                DE
              </button>
              <button
                type="button"
                className="lang-toggle__option"
                aria-pressed={lang === 'en'}
                onClick={() => setLang('en')}
              >
                EN
              </button>
              <button
                type="button"
                className="lang-toggle__option"
                aria-pressed={lang === 'ja'}
                onClick={() => setLang('ja')}
              >
                JP
              </button>
            </div>

            <button
              type="button"
              className="theme-toggle"
              data-theme={theme}
              aria-label={t.themeLabel}
              aria-pressed={theme === 'dark'}
              title={theme === 'dark' ? t.themeLight : t.themeDark}
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            >
              <svg
                className="theme-toggle__icon theme-toggle__icon--sun"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <circle cx="12" cy="12" r="4" />
                <g strokeLinecap="round">
                  <line x1="12" y1="2.5" x2="12" y2="5" />
                  <line x1="12" y1="19" x2="12" y2="21.5" />
                  <line x1="2.5" y1="12" x2="5" y2="12" />
                  <line x1="19" y1="12" x2="21.5" y2="12" />
                  <line x1="5.2" y1="5.2" x2="6.9" y2="6.9" />
                  <line x1="17.1" y1="17.1" x2="18.8" y2="18.8" />
                  <line x1="5.2" y1="18.8" x2="6.9" y2="17.1" />
                  <line x1="17.1" y1="6.9" x2="18.8" y2="5.2" />
                </g>
              </svg>
              <svg
                className="theme-toggle__icon theme-toggle__icon--moon"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z" />
              </svg>
            </button>
          </div>

          <dl className="atmosphere-strip" aria-label={t.heroAtmosphereEyebrow}>
            <div>
              <dt>{t.heroAtmosphereEyebrow}</dt>
              <dd>
                {atmosphereLabel(atmosphere, t)} · {formatTime(now, lang)} JST
              </dd>
            </div>
            <div>
              <dt>{t.weatherCity}</dt>
              <dd>{formatWeatherSummary(weather, lang, t)}</dd>
            </div>
            <div>
              <dt>{t.latestMeasurement}</dt>
              <dd className={latestTimestamp ? undefined : 'atmosphere-strip__fallback-value'}>
                {formatMeasurementTimestamp(latestTimestamp, lang, t)}
              </dd>
            </div>
            <div>
              <dt>{dataSourceEyebrow}</dt>
              <dd>
                <span
                  className={`status-pill${apiStatus === 'fallback' ? ' status-pill--fallback' : ''}`}
                  aria-hidden="true"
                >
                  {dataSourceLabel}
                </span>
              </dd>
            </div>
          </dl>
        </div>
      </header>

      {appView === 'campus' ? (
        <>
          <section className="campus-hero hero-strip" aria-label={t.campusHeadline} id="dashboard">
            <div className="hero-strip__cell">
              <p className="eyebrow">{t.campusHeadline}</p>
              <p className="hero-strip__metric">
                {totals.current}
                <span>{t.peopleUnit}</span>
              </p>
            </div>
            <div className="hero-strip__cell hero-strip__cell--forecast">
              <p className="eyebrow">
                {t.heroForecastEyebrow} · {formatTime(forecastTarget, lang)} JST
              </p>
              <p className="hero-strip__metric">
                {totals.forecast}
                <span>{t.peopleUnit}</span>
              </p>
            </div>
            <div className="hero-strip__cell">
              <p className="eyebrow">{t.statusEyebrow}</p>
              <p className="campus-status-text">{campusSummary.status}</p>
              <p className="source-note">
                {t.freshnessLabel}: {dataSourceLabel}
              </p>
            </div>
          </section>

          <section className="campus-grid">
            <div className="map-shell campus-map-shell" id="map">
              <div className="section-heading section-heading--map">
                <div className="map-heading-title">
                  <p className="eyebrow">{t.navMap}</p>
                  <h2>{t.campusMapTitle}</h2>
                </div>
                <div className="map-heading-actions">
                  <CampusModeSwitch mode={campusMapMode} onChange={setCampusMapMode} t={t} />
                </div>
              </div>
              <Legend t={t} />
              <CampusMap
                points={sensorPoints}
                heatmapPoints={heatmapPoints}
                mode={campusMapMode === 'heatmap' ? 'heatmap' : 'forecast'}
                t={t}
                theme={theme}
                lang={lang}
              />
            </div>

            <aside className="campus-insights" id="recommendations">
              <div className="section-heading compact">
                <div>
                  <p className="eyebrow">{t.recoEyebrow}</p>
                  <h2>{t.recoTitle}</h2>
                </div>
              </div>
              <div className="campus-insight-list">
                {campusSummary.busiest ? (
                  <article className="campus-insight campus-insight--busy">
                    <p className="eyebrow">{t.campusBusiest}</p>
                    <h3>{campusSummary.busiest.name[lang]}</h3>
                    <div className="campus-insight__metrics">
                      <span>
                        <small>{t.sensorMeasured}</small>
                        <strong>{campusSummary.busiest.measured}</strong>
                        <em>{t.peopleUnit}</em>
                      </span>
                      <span>
                        <small>{t.sensorForecast}</small>
                        <strong>{campusSummary.busiest.forecast}</strong>
                        <em>{t.peopleUnit}</em>
                      </span>
                    </div>
                  </article>
                ) : null}
                {campusSummary.quietest ? (
                  <article className="campus-insight campus-insight--calm">
                    <p className="eyebrow">{t.campusAlternative}</p>
                    <h3>{campusSummary.quietest.name[lang]}</h3>
                    <div className="campus-insight__metrics">
                      <span>
                        <small>{t.sensorMeasured}</small>
                        <strong>{campusSummary.quietest.measured}</strong>
                        <em>{t.peopleUnit}</em>
                      </span>
                      <span>
                        <small>{t.sensorForecast}</small>
                        <strong>{campusSummary.quietest.forecast}</strong>
                        <em>{t.peopleUnit}</em>
                      </span>
                    </div>
                  </article>
                ) : null}
              </div>
            </aside>
          </section>

          <SensorOverview sensorPoints={sensorPoints} t={t} lang={lang} showPrivacy={false} />
        </>
      ) : (
        <>
          <section
            className="hero-strip hero-strip--compact"
            aria-label={t.headerTitle}
            id="dashboard"
          >
            <div className="hero-strip__cell">
              <p className="eyebrow">{t.heroCurrentEyebrow}</p>
              <p className="hero-strip__metric">
                {totals.current}
                <span>{t.peopleUnit}</span>
              </p>
            </div>
            <div className="hero-strip__cell hero-strip__cell--forecast">
              <p className="eyebrow">
                {t.heroForecastEyebrow} · {formatTime(forecastTarget, lang)} JST
              </p>
              <p className="hero-strip__metric">
                {totals.forecast}
                <span>{t.peopleUnit}</span>
              </p>
            </div>
          </section>

          <section className="dashboard-grid">
            <div className="map-shell" id="map">
              <div className="section-heading section-heading--map">
                <div className="map-heading-title">
                  <p className="eyebrow">{t.mapEyebrow}</p>
                  <h2>{t.mapTitle}</h2>
                </div>
                <div className="map-heading-actions">
                  <MapModeSwitch mode={mapMode} onChange={setMapMode} t={t} />
                </div>
              </div>
              <Legend t={t} />
              {mapMode === '3d' ? (
                <CampusScene t={t} theme={theme} />
              ) : (
                <CampusMap
                  points={sensorPoints}
                  heatmapPoints={heatmapPoints}
                  mode={mapMode}
                  t={t}
                  theme={theme}
                  lang={lang}
                />
              )}
            </div>

            <aside className="side-panel" id="forecast">
              <div className="section-heading compact">
                <div>
                  <p className="eyebrow">{t.extrapEyebrow}</p>
                  <h2>{t.extrapTitle}</h2>
                </div>
              </div>
              <Sparkline measured={measuredHours} forecast={forecastHours} t={t} />
              <div className="sparkline-legend" aria-hidden="true">
                <span className="sparkline-legend__measured" /> {t.extrapMeasured}
                <span className="sparkline-legend__forecast" /> {t.extrapForecast}
              </div>
              <ul className="method-list">
                <li>{t.extrapMethodPchip}</li>
                <li>{t.extrapMethodGaussian}</li>
                <li>{t.extrapMethodFourier}</li>
              </ul>
            </aside>
          </section>

          <SensorOverview sensorPoints={sensorPoints} t={t} lang={lang} />

          <section className="lower-grid">
            <TeamBIntegrationPanel status={modelStatus} t={t} lang={lang} />

            <div className="recommendations" id="recommendations">
              <div className="section-heading compact">
                <div>
                  <p className="eyebrow">{t.recoEyebrow}</p>
                  <h2>{t.recoTitle}</h2>
                </div>
              </div>
              <ol className="recommendation-list">
                {recommendations.map((item, index) => (
                  <li className="recommendation-row" key={item.place.en}>
                    <span className="recommendation-row__order" aria-hidden="true">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <div>
                      <h3>{item.place[lang]}</h3>
                      <p>{item.reason[lang]}</p>
                    </div>
                    <span
                      className="recommendation-row__chip"
                      aria-label={`${t.recoEyebrow}: ${item.priority}`}
                    >
                      {item.priority === 'hoch'
                        ? t.recoPriorityHigh
                        : item.priority === 'mittel'
                          ? t.recoPriorityMid
                          : t.recoPriorityLow}
                    </span>
                  </li>
                ))}
              </ol>
            </div>

            <div className="stack-panel" id="stack">
              <div className="section-heading compact">
                <div>
                  <p className="eyebrow">{t.stackEyebrow}</p>
                  <h2>{t.stackTitle}</h2>
                </div>
              </div>
              <dl className="stack-list">
                {stackItems.map(([label, value]) => (
                  <div key={label.en}>
                    <dt>{label[lang]}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
