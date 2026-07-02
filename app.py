from __future__ import annotations

from datetime import date, time
import json
import os
from pathlib import Path
import re

import folium
import streamlit as st
from streamlit_folium import st_folium

from metriklim.catalog import ANALYSES, ANALYSIS_METHODS, SOURCES, VARIABLES
from metriklim.artifacts import (
    build_area_map_png,
    build_complete_package,
    build_excel,
    build_raster_png,
    build_timeseries_png,
    dataframe_to_csv,
    geodata_to_gpkg,
)
from metriklim.climate_engine import (
    connection_label,
    fetch_timeseries as fetch_climate_engine_timeseries,
    validate_api_key,
)
from metriklim.exports import build_metadata
from metriklim.geometry import GeometryUploadError, UploadedPart, inspect_uploaded_files
from metriklim.gee import (
    build_climate_geotiff,
    build_chirps_spi_geotiff,
    build_remote_analysis_geotiff,
    fetch_chirps_monthly_mean,
    fetch_gee_monthly_climate,
    create_user_auth_flow,
    exchange_user_auth_code,
    initialize_gee,
)
from metriklim.open_meteo import fetch_centroid_series
from metriklim.spi import calculate_spi_table


ROOT = Path(__file__).parent
LOGO = ROOT / "assets" / "metriklim-logo-v2.png"

st.set_page_config(
    page_title="Metriklim | Coğrafi iklim analizi",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="collapsed",
)

access_code = os.getenv("METRIKLIM_ACCESS_CODE")
if access_code and not st.session_state.get("access_granted"):
    st.title("Metriklim")
    st.caption("Bu paylaşım GEE kotasını korumak için erişim koduyla sınırlandırılmıştır.")
    entered_code = st.text_input("Erişim kodu", type="password")
    if st.button("Uygulamaya gir", type="primary", use_container_width=True):
        if entered_code == access_code:
            st.session_state.access_granted = True
            st.rerun()
        else:
            st.error("Erişim kodu hatalı.")
    st.stop()


def cached_gee_status(project: str | None) -> tuple[bool, str]:
    return initialize_gee(project)

st.markdown(
    """
    <style>
    :root { --ink:#062f40; --teal:#00a6a6; --cyan:#35c8d0; --amber:#ffad33; --coral:#ef6c57; }
    .stApp {
      background:
        radial-gradient(circle at 92% 8%, rgba(69,214,196,.20), transparent 24rem),
        radial-gradient(circle at 8% 92%, rgba(255,183,77,.15), transparent 22rem),
        linear-gradient(180deg, #f3fbf9 0%, #fffaf0 100%);
    }
    [data-testid="stHeader"] { background: transparent; }
    .block-container { max-width: 1420px; padding-top: 1.25rem; }
    .hero {
      background: linear-gradient(120deg, #102f46 0%, #075b68 52%, #00a68f 100%);
      color: white; border-radius: 28px; padding: 32px 36px; margin-bottom: 18px;
      position: relative; overflow: hidden; box-shadow: 0 18px 50px rgba(6,47,64,.16);
    }
    .hero:before, .hero:after {
      content:""; position:absolute; border-radius:46% 54% 58% 42%;
      border:1px solid rgba(126,241,234,.38); transform:rotate(18deg);
    }
    .hero:before { width:340px; height:340px; right:-70px; top:-150px; }
    .hero:after { width:210px; height:210px; right:40px; bottom:-160px; }
    .eyebrow { color:#ffd27a; font-size:.76rem; letter-spacing:.16em; font-weight:850; }
    .hero h1 { font-size:2.35rem; line-height:1.04; margin:.42rem 0 .6rem; max-width:850px; }
    .hero p { color:#d7f2ef; max-width:820px; margin:0; font-size:1rem; }
    .step {
      font-size:.72rem; letter-spacing:.12em; color:#147984;
      text-transform:uppercase; font-weight:850; margin-bottom:.25rem;
    }
    .hint {
      background:linear-gradient(90deg, rgba(0,166,166,.10), rgba(53,200,208,.05));
      border-left:4px solid var(--teal); padding:12px 14px; border-radius:8px;
      color:#315b64; margin:.5rem 0 1rem;
    }
    .status-ready { color:#07806d; font-weight:800; }
    .status-wait { color:#b36b00; font-weight:800; }
    div[data-testid="stMetric"] {
      background:rgba(255,255,255,.82); border:1px solid rgba(0,128,136,.20);
      padding:12px 14px; border-radius:16px; box-shadow:0 6px 18px rgba(6,47,64,.05);
    }
    button[data-baseweb="tab"] { font-weight:750; }
    div[data-baseweb="tab-list"] {
      background:rgba(255,255,255,.72); padding:.35rem; border-radius:16px;
      border:1px solid rgba(0,128,136,.15);
    }
    .workflow { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:4px 0 20px; }
    .flow-card {
      background:rgba(255,255,255,.82); border:1px solid rgba(0,128,136,.18);
      border-radius:16px; padding:13px 14px; box-shadow:0 7px 20px rgba(6,47,64,.05);
    }
    .flow-card b { color:#075b68; display:block; margin-bottom:3px; }
    .flow-card span { color:#55727a; font-size:.82rem; }
    @media (max-width:800px) { .workflow { grid-template-columns:1fr 1fr; } }
    .stButton > button, .stDownloadButton > button {
      border-radius:999px; min-height:2.85rem; font-weight:780;
    }
    .stButton > button[kind="primary"] {
      background:linear-gradient(90deg, #008f91, #00b7ad); border:0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if "uploader_nonce" not in st.session_state:
    st.session_state.uploader_nonce = 0

top_logo, top_hero = st.columns([0.16, 0.84], vertical_alignment="center")
with top_logo:
    st.image(str(LOGO), width=150)
with top_hero:
    st.markdown(
        """
        <section class="hero">
          <h1>Havzanı tanımla, iklim ve çevresel değişimi birlikte analiz et.</h1>
          <p>Çalışma alanını yükle; veri kaynağını, inceleme dönemini ve analiz yöntemlerini seç.
          Metriklim sonuçlarını harita, GeoTIFF, Excel ve CBS'ye hazır proje paketi olarak oluştursun.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )

st.markdown(
    """
    <div class="workflow">
      <div class="flow-card"><b>1 · Alanı yükle</b><span>SHP, GeoPackage veya GeoJSON</span></div>
      <div class="flow-card"><b>2 · Veriyi seç</b><span>CHIRPS, ERA5-Land ve açık kaynaklar</span></div>
      <div class="flow-card"><b>3 · Analizi kur</b><span>SPI ölçeği, dönem ve yöntem</span></div>
      <div class="flow-card"><b>4 · CBS çıktısını al</b><span>Excel, GeoPackage, GeoTIFF ve harita</span></div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_area, tab_data, tab_analysis, tab_output = st.tabs(
    ["01 · Çalışma Alanı", "02 · Veri Kaynakları", "03 · Analiz Tasarımı", "04 · Bulgular ve Çıktılar"]
)

with tab_area:
    left, right = st.columns([0.43, 0.57], gap="large")
    with left:
        st.markdown('<div class="step">Çalışma alanı</div>', unsafe_allow_html=True)
        st.subheader("Coğrafi sınırınızı ekleyin")
        st.markdown(
            '<div class="hint">ZIP zorunlu değil. GeoPackage veya GeoJSON tek dosya; '
            'Shapefile ise .shp, .shx, .dbf ve .prj bileşenleri birlikte seçilebilir.</div>',
            unsafe_allow_html=True,
        )
        uploads = st.file_uploader(
            "Çalışma alanı dosyaları",
            type=["zip", "shp", "shx", "dbf", "prj", "cpg", "gpkg", "geojson", "json"],
            accept_multiple_files=True,
            key=f"area_upload_{st.session_state.uploader_nonce}",
            help="Havza, il, ilçe, bölge veya kendi çizdiğiniz poligonları yükleyin.",
        )
        single_shp_crs = st.text_input(
            "Tek SHP için koordinat sistemi",
            value="EPSG:4326",
            help=(
                "Yalnız .shp yüklenirse .prj bulunmadığı için CRS burada belirtilir. "
                "GeoPackage, GeoJSON ve tam SHP paketinde dosyanın kendi CRS bilgisi kullanılır."
            ),
        )
        clear_col, info_col = st.columns([0.42, 0.58], vertical_alignment="center")
        with clear_col:
            if st.button("Dosyaları temizle", icon=":material/delete:", use_container_width=True):
                st.session_state.pop("geometry_summary", None)
                st.session_state.pop("output_package", None)
                st.session_state.uploader_nonce += 1
                st.rerun()
        with info_col:
            st.caption("Hatalı dosyayı yükleme kutusundaki × ile tek tek de silebilirsiniz.")

        summary = st.session_state.get("geometry_summary")
        if uploads:
            try:
                parts = [UploadedPart(item.name, item.getvalue()) for item in uploads]
                with st.spinner("Geometri, koordinat sistemi ve alan denetleniyor..."):
                    summary = inspect_uploaded_files(parts, fallback_crs=single_shp_crs)
                st.session_state.geometry_summary = summary
            except GeometryUploadError as exc:
                summary = None
                st.session_state.pop("geometry_summary", None)
                st.error(str(exc))

        if summary:
            m1, m2 = st.columns(2)
            m1.metric("Toplam alan", f"{summary.area_km2:,.2f} km²")
            m2.metric("Coğrafi obje", f"{summary.feature_count:,}")
            st.success("Çalışma alanı doğrulandı.")

            with st.expander("Alan detayları", expanded=True):
                d1, d2 = st.columns(2)
                d1.write(f"**Çevre:** {summary.perimeter_km:,.2f} km")
                d1.write(f"**Köşe sayısı:** {summary.vertex_count:,}")
                d1.write(f"**Kaynak CRS:** {summary.source_crs}")
                d2.write(f"**Alan hesabı CRS:** {summary.area_crs}")
                d2.write(f"**Merkez:** {summary.centroid[0]:.5f}, {summary.centroid[1]:.5f}")
                d2.write(f"**Geometri onarımı:** {'Uygulandı' if summary.was_repaired else 'Gerekmedi'}")

            spatial_mode = st.selectbox(
                "Analiz alanı detayı",
                [
                    "Tüm objeleri tek çalışma alanı olarak birleştir",
                    "Her coğrafi objeyi ayrı raporla",
                    "Her obje + tüm alan özetini birlikte üret",
                    "Yalnızca alan ortalaması üret",
                ],
                help="Çok parçalı ilçe veya alt havza verilerinde sonuçların nasıl gruplanacağını belirler.",
            )
            spatial_stat = st.multiselect(
                "Mekânsal özetler",
                ["Ortalama", "Toplam", "Minimum", "Maksimum", "Medyan", "Standart sapma", "Yüzdelikler"],
                default=["Ortalama", "Minimum", "Maksimum"],
            )
        else:
            spatial_mode = "Tüm objeleri tek çalışma alanı olarak birleştir"
            spatial_stat = ["Ortalama"]
            st.info("Harita ve alan ayrıntıları için bir coğrafi dosya yükleyin.")

    with right:
        st.markdown('<div class="step">Harita önizleme</div>', unsafe_allow_html=True)
        if summary:
            bounds = summary.bounds
            fmap = folium.Map(summary.centroid, zoom_start=8, tiles="CartoDB positron")
            folium.GeoJson(
                summary.gdf_wgs84.__geo_interface__,
                style_function=lambda _: {
                    "color": "#063447", "weight": 3, "fillColor": "#00a6a6", "fillOpacity": 0.30
                },
                highlight_function=lambda _: {"weight": 5, "fillOpacity": 0.42},
                tooltip=folium.GeoJsonTooltip(
                    fields=[c for c in summary.gdf_wgs84.columns if c != "geometry"][:4],
                    aliases=[c for c in summary.gdf_wgs84.columns if c != "geometry"][:4],
                ) if len(summary.gdf_wgs84.columns) > 1 else None,
            ).add_to(fmap)
            fmap.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
        else:
            fmap = folium.Map([39.0, 35.0], zoom_start=5, tiles="CartoDB positron")
        st_folium(fmap, height=570, width="stretch", returned_objects=[])

with tab_data:
    st.markdown('<div class="step">Kaynak, ürün ve değişken</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="hint">Metriklim tek bir servise bağlı değildir. Climate Engine, '
        'Copernicus, NASA, NOAA, ESA, USGS ve doğrudan açık veri ürünleri aynı iş akışında seçilebilir.</div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3, gap="large")
    climate_engine_key = st.session_state.get(
        "climate_engine_api_key",
        os.getenv("CLIMATE_ENGINE_API_KEY", ""),
    )
    with c1:
        source_options = list(SOURCES)
        provider = st.selectbox(
            "Veri kaynağı",
            source_options,
            index=source_options.index("Google Earth Engine"),
        )
        source_info = SOURCES[provider]
        st.caption(source_info["description"])
        status_class = "status-ready" if source_info["status"] in {"Hazır", "Açık erişim"} else "status-wait"
        st.markdown(f'<span class="{status_class}">● {source_info["status"]}</span>', unsafe_allow_html=True)
        if provider == "Climate Engine":
            st.markdown("##### Climate Engine hesabını bağlayın")
            st.caption(
                "Climate Engine kullanıcı girişi Project ID ile değil, kişiye özel API anahtarıyla yapılır."
            )
            entered_ce_key = st.text_input(
                "Climate Engine API anahtarı",
                value="",
                type="password",
                placeholder="Anahtarınızı buraya yapıştırın",
                help="Anahtar yalnız bu tarayıcı oturumunda tutulur; GitHub'a ve çıktı dosyalarına yazılmaz.",
            )
            ce_left, ce_right = st.columns(2)
            ce_left.link_button(
                "API anahtarı iste",
                "https://www.climateengine.org/apis/requesting-an-authorization-key-token/",
                use_container_width=True,
            )
            ce_right.link_button(
                "Resmî API belgeleri",
                "https://api.climateengine.org/",
                use_container_width=True,
            )
            if st.button(
                "Climate Engine bağlantısını doğrula",
                disabled=not entered_ce_key,
                use_container_width=True,
            ):
                try:
                    with st.spinner("Climate Engine anahtarı doğrulanıyor..."):
                        ce_status = validate_api_key(entered_ce_key)
                    st.session_state.climate_engine_api_key = entered_ce_key
                    st.session_state.climate_engine_status = ce_status
                    st.success("Climate Engine API anahtarı doğrulandı.")
                    st.rerun()
                except Exception as ce_error:
                    st.session_state.pop("climate_engine_api_key", None)
                    st.session_state.pop("climate_engine_status", None)
                    st.error(f"Climate Engine bağlantısı kurulamadı: {ce_error}")
            climate_engine_key = st.session_state.get(
                "climate_engine_api_key",
                os.getenv("CLIMATE_ENGINE_API_KEY", ""),
            )
            if climate_engine_key:
                st.success(f"Climate Engine · {connection_label(climate_engine_key)}")
                expiration = st.session_state.get("climate_engine_status", {}).get("expiration")
                if expiration:
                    st.caption(f"Anahtar geçerlilik bilgisi: {expiration}")
                if st.button("Climate Engine bağlantısını kes", use_container_width=True):
                    st.session_state.pop("climate_engine_api_key", None)
                    st.session_state.pop("climate_engine_status", None)
                    st.rerun()
        gee_project = (
            st.text_input(
                "Google Earth Engine Project ID",
                value=os.getenv("GOOGLE_EARTH_ENGINE_PROJECT", ""),
                placeholder="ör. ee-kullanici-projesi",
                help="Proje adı veya numarası değil, Google Cloud Project ID değerini girin.",
            )
            if provider == "Google Earth Engine"
            else os.getenv("GOOGLE_EARTH_ENGINE_PROJECT", "")
        )
        if provider == "Google Earth Engine":
            project_valid = bool(
                re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", gee_project or "")
            )
            with st.expander("Project ID nasıl alınır?", expanded=not project_valid):
                st.markdown(
                    """
                    1. Google Cloud'da bir proje oluşturun veya mevcut projenizi seçin.
                    2. **Project ID** değerini proje seçiciden kopyalayın; proje adı ve proje numarası farklıdır.
                    3. Earth Engine API'yi etkinleştirin.
                    4. Projeyi ticari olmayan araştırma veya uygun kullanım türüyle Earth Engine'e kaydedin.
                    5. Buraya Project ID'yi girip Google hesabınızla yetkilendirin.
                    """
                )
                st.link_button(
                    "1 · Google Cloud projesi oluştur",
                    "https://console.cloud.google.com/projectcreate",
                    use_container_width=True,
                )
                if project_valid:
                    st.link_button(
                        "2 · Earth Engine API'yi etkinleştir",
                        "https://console.cloud.google.com/apis/library/earthengine.googleapis.com"
                        f"?project={gee_project}",
                        use_container_width=True,
                    )
                    st.link_button(
                        "3 · Projeyi Earth Engine'e kaydet",
                        "https://console.cloud.google.com/earth-engine/configuration"
                        f"?project={gee_project}",
                        use_container_width=True,
                    )
                    st.caption(
                        "Kayıt sayfasına yönlendirilmeniz normaldir; bu adım Google girişi değil, "
                        "Project ID'nin Earth Engine kullanımına açılmasıdır."
                    )

            if gee_project and not project_valid:
                st.error(
                    "Project ID biçimi geçerli görünmüyor. Yalnızca küçük harf, rakam ve kısa çizgi kullanın."
                )
                gee_ok, gee_message = False, "Geçersiz Project ID"
            elif project_valid:
                gee_ok, gee_message = cached_gee_status(gee_project)
                personal_auth = st.session_state.get("gee_user_auth", {})
                personally_connected = personal_auth.get("project") == gee_project
                if gee_ok and personally_connected:
                    st.success(f"Earth Engine {gee_message}")
                    if st.button("Google bağlantısını kes", use_container_width=True):
                        st.session_state.pop("gee_user_auth", None)
                        st.session_state.pop("gee_auth_flow", None)
                        st.rerun()
                elif gee_ok:
                    st.success(f"Earth Engine {gee_message}")
                    st.caption("Sunucu bağlantısı hazır. İsterseniz kendi Google hesabınızı bağlayabilirsiniz.")
                else:
                    st.warning("Bu Project ID için geçerli Google yetkilendirmesi bulunamadı.")

                if not personally_connected:
                    if st.button(
                        "Google hesabıyla Earth Engine'e bağlan",
                        type="primary",
                        use_container_width=True,
                    ):
                        auth_url, verifier = create_user_auth_flow()
                        st.session_state.gee_auth_flow = {
                            "project": gee_project,
                            "url": auth_url,
                            "verifier": verifier,
                        }
                    auth_flow = st.session_state.get("gee_auth_flow")
                    if auth_flow and auth_flow.get("project") == gee_project:
                        st.link_button(
                            "Google giriş ve izin ekranını aç",
                            auth_flow["url"],
                            use_container_width=True,
                        )
                        auth_code = st.text_input(
                            "Google'ın verdiği tek kullanımlık doğrulama kodu",
                            type="password",
                            help="Kod yalnızca bu oturumda bağlantı kurmak için kullanılır ve dosyaya yazılmaz.",
                        )
                        if st.button(
                            "Bağlantıyı tamamla ve test et",
                            disabled=not auth_code,
                            use_container_width=True,
                        ):
                            try:
                                with st.spinner("Google Earth Engine bağlantısı doğrulanıyor..."):
                                    st.session_state.gee_user_auth = exchange_user_auth_code(
                                        auth_code,
                                        auth_flow["verifier"],
                                        gee_project,
                                    )
                                st.session_state.pop("gee_auth_flow", None)
                                st.success("Google hesabı ve Project ID başarıyla doğrulandı.")
                                st.rerun()
                            except Exception as auth_error:
                                st.error(
                                    "Bağlantı kurulamadı. Project ID, Earth Engine kaydı ve Google "
                                    f"hesabı izinlerini kontrol edin. Ayrıntı: {auth_error}"
                                )
            else:
                gee_ok, gee_message = False, "Project ID bekleniyor"
                st.info("Önce kendi Google Cloud Project ID değerinizi girin.")
    with c2:
        product = st.selectbox("Veri ürünü", source_info["products"])
        ce_dataset_defaults = {
            "CHIRPS Daily": ("CHIRPS_DAILY", "precipitation"),
            "CHIRPS Pentad": ("CHIRPS_PENTAD", "precipitation"),
            "ERA5": ("ERA5", ""),
            "ERA5-Land": ("ERA5_LAND", ""),
        }
        if provider == "Climate Engine":
            default_dataset, default_variables = ce_dataset_defaults.get(product, (product, ""))
            ce_dataset_id = st.text_input(
                "Climate Engine dataset parametresi",
                value=default_dataset,
                help="Resmî Climate Engine Datasets & Variables sayfasındaki Dataset Parameter değeri.",
            )
            ce_variable_ids = st.text_input(
                "Climate Engine değişken parametreleri",
                value=default_variables,
                placeholder="ör. precipitation veya NDVI, EVI",
                help="Birden fazla değişkeni virgülle ayırabilirsiniz.",
            )
            st.link_button(
                "Dataset ve değişken parametrelerini incele",
                "https://www.climateengine.org/apis/apiDatasets/",
                use_container_width=True,
            )
        else:
            ce_dataset_id, ce_variable_ids = "", ""
        variables = st.multiselect(
            "Değişkenler",
            list(VARIABLES),
            default=["Yağış", "Hava sıcaklığı"],
        )
        quality_control = st.multiselect(
            "Kalite kontrolleri",
            ["Eksik veri", "Aykırı değer", "Birim dönüşümü", "Zaman sürekliliği", "Kaynaklar arası karşılaştırma"],
            default=["Eksik veri", "Birim dönüşümü", "Zaman sürekliliği"],
        )
    with c3:
        period_mode = st.radio(
            "Dönem tanımlama",
            ["Yıl aralığı", "Kesin tarih aralığı"],
            horizontal=True,
            help="Yıl aralığında başlangıç 1 Ocak, bitiş 31 Aralık olarak uygulanır.",
        )
        if period_mode == "Yıl aralığı":
            year_left, year_right = st.columns(2)
            start_year = year_left.number_input(
                "Başlangıç yılı",
                min_value=1900,
                max_value=date.today().year,
                value=1981,
                step=1,
            )
            end_year = year_right.number_input(
                "Bitiş yılı",
                min_value=1900,
                max_value=date.today().year,
                value=date.today().year,
                step=1,
            )
            start_date = date(int(start_year), 1, 1)
            end_date = (
                date.today()
                if int(end_year) == date.today().year
                else date(int(end_year), 12, 31)
            )
            st.caption(f"Uygulanacak dönem: {start_date:%d.%m.%Y} – {end_date:%d.%m.%Y}")
        else:
            start_date = st.date_input("Başlangıç tarihi", date(1981, 1, 1))
            end_date = st.date_input("Bitiş tarihi", date.today())
        temporal_scale = st.selectbox(
            "Zaman çözünürlüğü",
            ["Saatlik", "3 saatlik", "6 saatlik", "Günlük", "Haftalık", "Aylık", "Mevsimlik", "Yıllık"],
            index=3,
        )
        if temporal_scale in {"Saatlik", "3 saatlik", "6 saatlik"}:
            start_time = st.time_input("Başlangıç saati", time(0, 0))
            end_time = st.time_input("Bitiş saati", time(23, 0))
        else:
            start_time, end_time = None, None
        aggregation = st.selectbox(
            "Zamansal özet",
            ["Kaynağın doğal değeri", "Ortalama", "Toplam", "Minimum", "Maksimum", "Medyan", "Yüzdelik"],
        )
        if start_date > end_date:
            st.error("Başlangıç yılı/tarihi bitiş değerinden sonra olamaz.")

    st.divider()
    st.subheader("Ürün–değişken uygunluk denetimi")
    rows = []
    for variable in variables:
        suggestions = VARIABLES[variable]
        rows.append(
            {
                "Değişken": variable,
                "Seçili ürün": product,
                "Önerilen ürünler": ", ".join(suggestions),
                "Kontrol": "Doğrudan uygun" if any(p in product or product in p for p in suggestions) else "Alternatif ürün önerilir",
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)

with tab_analysis:
    st.markdown('<div class="step">Bilimsel yöntem seçimi ve analiz tasarımı</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="hint"><strong>Birden fazla modülü birlikte çalıştırabilirsiniz.</strong> '
        'Örneğin SPI-3 + NDVI + LST + TWI seçimi, kuraklık sinyalini bitki, yüzey sıcaklığı '
        've topoğrafik nem potansiyeliyle aynı pakette karşılaştırır.</div>',
        unsafe_allow_html=True,
    )
    operational_methods = {
        "SPI", "NDVI", "NDWI", "NDMI", "NDBI", "EVI", "SAVI",
        "LST", "DEM", "SLOPE", "ASPECT", "TWI",
    }
    operational_families = [
        "Kuraklık indisleri",
        "Uzaktan algılama indisleri",
        "Topoğrafik ve hidrolojik türevler",
    ]
    selected_families = st.multiselect(
        "Analiz modülleri",
        operational_families,
        default=operational_families,
        help="Yöntem listesini daraltmak için bir veya daha fazla bilimsel analiz ailesi seçin.",
    )
    available_methods = list(
        dict.fromkeys(
            method
            for family in selected_families
            for method in ANALYSES[family]
            if method in operational_methods
        )
    )
    selected_analyses = st.multiselect(
        "Uygulanacak analizler",
        available_methods,
        default=["SPI"] if "SPI" in available_methods else [],
        help="Her seçim çıktı paketine ayrı yöntem ve kaynak kaydıyla eklenir.",
    )

    documented_methods = [
        {"Kod": method, **ANALYSIS_METHODS[method]}
        for method in selected_analyses
        if method in ANALYSIS_METHODS
    ]
    if documented_methods:
        with st.expander("Seçilen yöntemlerin bilimsel kimliği", expanded=True):
            st.dataframe(
                [
                    {
                        "Yöntem": row["Kod"],
                        "Tam ad": row["title"],
                        "Birincil ürün": row["source"],
                        "Doğal çözünürlük": row["resolution"],
                        "Analitik amaç": row["purpose"],
                    }
                    for row in documented_methods
                ],
                width="stretch",
                hide_index=True,
            )

    st.subheader("Ortak araştırma ayarları")
    a1, a2, a3, a4 = st.columns(4)
    with a1:
        baseline = st.selectbox("Referans dönem", ["1991–2020", "1981–2010", "1961–1990", "Tüm dönem", "Özel"])
    with a2:
        significance = st.selectbox("Anlamlılık düzeyi (α)", ["0.05", "0.01", "0.10"])
    with a3:
        missing_method = st.selectbox("Eksik veri yaklaşımı", ["Analiz dışı bırak", "Doğrusal enterpolasyon", "Komşu dönem ortalaması"])
    with a4:
        seasonal_filter = st.multiselect("Ay/mevsim filtresi", ["İlkbahar", "Yaz", "Sonbahar", "Kış"], placeholder="Tümü")

    analysis_params = {
        "families": selected_families,
        "baseline": baseline,
        "significance": significance,
        "missing_method": missing_method,
        "seasonal_filter": seasonal_filter,
    }

    if any(method in selected_analyses for method in ANALYSES["Kuraklık indisleri"]):
        st.markdown("##### Kuraklık analizi parametreleri")
        p1, p2, p3 = st.columns(3)
        with p1:
            analysis_params["scales"] = st.multiselect("İndeks ölçeği (ay)", [1, 2, 3, 6, 9, 12, 18, 24, 36, 48], default=[1, 3, 6, 12])
        with p2:
            analysis_params["distribution"] = st.selectbox("Olasılık dağılımı", ["Gamma", "Pearson Tip III", "Log-lojistik", "Otomatik en iyi uyum"])
        with p3:
            analysis_params["pet_method"] = st.selectbox("PET yöntemi (SPEI/PDSI)", ["FAO-56 Penman–Monteith", "Hargreaves", "Thornthwaite"])
    if any(method in selected_analyses for method in ANALYSES["Uzaktan algılama indisleri"]):
        st.markdown("##### Uydu görüntüsü ve kompozit parametreleri")
        p1, p2, p3 = st.columns(3)
        analysis_params["cloud_limit"] = p1.slider(
            "Azami sahne bulutluluğu (%)", 0, 80, 30, 5
        )
        analysis_params["composite"] = p2.selectbox(
            "Dönem kompoziti", ["Medyan"], help="Medyan kompozit artık bulut ve uç değer etkisini azaltır."
        )
        analysis_params["savi_l"] = p3.number_input(
            "SAVI toprak düzeltme katsayısı (L)", 0.0, 1.0, 0.5, 0.1,
            help="Mevcut hesap motorunda standart L=0,5 uygulanır.",
        )
        st.caption(
            "NDVI/NDWI/EVI/SAVI 10 m; NDMI/NDBI 20 m Sentinel-2 L2A. "
            "LST, Landsat 8/9 Collection 2 Level-2 yüzey sıcaklığıdır."
        )

    if "Eğilim ve homojenlik" in selected_families:
        p1, p2 = st.columns(2)
        analysis_params["autocorrelation"] = p1.selectbox("Seri bağımlılığı", ["Ön beyazlatma", "Trend-free pre-whitening", "Düzeltme yok"])
        analysis_params["trend_unit"] = p2.selectbox("Eğim raporlama birimi", ["Yıl başına", "10 yıl başına", "Tüm dönem"])
    if "İklim uçları (ETCCDI)" in selected_families:
        p1, p2 = st.columns(2)
        analysis_params["percentile_period"] = p1.selectbox("Yüzdelik referansı", ["1991–2020", "1981–2010", "Özel"])
        analysis_params["wet_day_threshold"] = p2.number_input("Islak gün eşiği (mm)", 0.1, 20.0, 1.0, 0.1)
    if "Mekânsal istatistik" in selected_families:
        p1, p2, p3 = st.columns(3)
        analysis_params["resolution"] = p1.number_input("Çıktı pikseli (m)", 10, 100000, 1000, 10)
        analysis_params["neighbors"] = p2.selectbox("Komşuluk", ["Queen", "Rook", "Mesafe bandı", "K-en yakın"])
        analysis_params["interpolation"] = p3.selectbox("Enterpolasyon ayarı", ["Otomatik", "Doğal komşu", "Varyogram ile"])
    if "Föhn ve topoğrafya" in selected_families:
        p1, p2, p3 = st.columns(3)
        analysis_params["ridge_direction"] = p1.number_input("Sırt doğrultusu (°)", 0, 359, 90)
        analysis_params["temp_threshold"] = p2.number_input("Sıcaklık farkı eşiği (°C)", 0.0, 20.0, 2.0, 0.5)
        analysis_params["rh_threshold"] = p3.number_input("Nem farkı eşiği (%)", 0, 100, 10)

    st.info(
        f"{len(selected_families)} modülden {len(selected_analyses)} analiz seçildi. "
        "Her raster çalışma alanı sınırına kırpılacak; kaynak, formül, dönem ve çözünürlük metadata dosyasına yazılacaktır."
    )
    st.success(
        "Bu ekrandaki 12 yöntem çalışır durumdadır; yalnızca gerçek açık veri koleksiyonları kullanılır."
    )

with tab_output:
    st.markdown('<div class="step">İşlemi oluştur ve indir</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="hint">
          <strong>Dosya nereye kaydedilir?</strong><br>
          İndir düğmesine bastığınızda dosya tarayıcınızın varsayılan
          <strong>İndirilenler (Downloads)</strong> klasörüne kaydedilir.
          Tarayıcınız “Her indirmede konum sor” ayarındaysa hedef klasörü siz seçersiniz.
          Metriklim dosyayı sunucuda kalıcı olarak saklamaz.
        </div>
        """,
        unsafe_allow_html=True,
    )
    summary = st.session_state.get("geometry_summary")
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Alan", f"{summary.area_km2:,.2f} km²" if summary else "Bekleniyor")
    q2.metric("Kaynak", provider)
    q3.metric("Değişken", len(variables))
    q4.metric("Yöntem", len(selected_analyses))

    output_formats = st.multiselect(
        "İstenen çıktılar",
        ["Proje paketi (ZIP)", "CSV zaman serisi", "Excel çalışma kitabı", "GeoTIFF raster", "GeoPackage", "GeoJSON", "PNG harita", "PDF rapor"],
        default=["Proje paketi (ZIP)", "CSV zaman serisi", "Excel çalışma kitabı", "GeoPackage", "GeoJSON", "PNG harita"],
    )
    include_items = st.multiselect(
        "Pakete eklenecek içerik",
        ["Ham veri", "İşlenmiş veri", "Analiz sonuçları", "Grafikler", "Kaynak ve yöntem metadata", "Kalite kontrol raporu"],
        default=["Analiz sonuçları", "Kaynak ve yöntem metadata", "Kalite kontrol raporu"],
    )

    source_ready = (
        bool(climate_engine_key and ce_dataset_id and ce_variable_ids)
        if provider == "Climate Engine"
        else True
    )
    can_build = bool(
        summary and variables and selected_analyses and start_date <= end_date and source_ready
    )
    if not summary:
        st.warning("Önce Alan sekmesinden geçerli bir çalışma alanı yükleyin.")
    if not selected_analyses:
        st.warning("Analiz sekmesinden en az bir yöntem seçin.")
    if provider == "Climate Engine" and not source_ready:
        st.warning(
            "Climate Engine işlemi için doğrulanmış API anahtarı, dataset parametresi "
            "ve en az bir değişken parametresi gereklidir."
        )

    if st.button(
        "İşlemi oluştur",
        type="primary",
        icon=":material/play_arrow:",
        disabled=not can_build,
        use_container_width=True,
    ):
        live_supported = provider in {
            "Otomatik en uygun açık kaynak",
            "Open-Meteo Historical",
            "Google Earth Engine",
            "Climate Engine",
        }
        if not live_supported:
            st.error(
                f"{provider} için canlı indirme bağlayıcısı henüz etkin değil. "
                "Gerçek veri almak için şimdilik “Otomatik en uygun açık kaynak” "
                "veya “Open-Meteo Historical” seçin."
            )
        else:
            try:
                with st.spinner("Seçilen kaynaktan gerçek veri indiriliyor ve çıktılar hazırlanıyor..."):
                    if provider == "Google Earth Engine":
                        if "SPI" in selected_analyses and "Yağış" not in variables:
                            raise ValueError(
                                "Google Earth Engine/CHIRPS akışında SPI için Yağış değişkenini seçin."
                            )
                        climate_data, unsupported = fetch_gee_monthly_climate(
                            summary.gdf_wgs84,
                            start_date,
                            end_date,
                            variables,
                            project=gee_project,
                        )
                        climate_model = "CHIRPS Daily + ERA5-Land via Google Earth Engine"
                        climate_url = (
                            "https://developers.google.com/earth-engine/datasets/catalog/"
                            "UCSB-CHG_CHIRPS_DAILY"
                        )
                        climate_latitude, climate_longitude = summary.centroid
                        climate_elevation = None
                        if unsupported:
                            try:
                                fallback = fetch_centroid_series(
                                    latitude=summary.centroid[0],
                                    longitude=summary.centroid[1],
                                    start_date=start_date,
                                    end_date=end_date,
                                    variables=unsupported,
                                    temporal_scale="Aylık",
                                )
                                fallback_columns = [
                                    column for column in fallback.data.columns
                                    if column not in {"Örnek ID", "Enlem", "Boylam"}
                                ]
                                climate_data = climate_data.merge(
                                    fallback.data[fallback_columns],
                                    on="Tarih",
                                    how="outer",
                                )
                                unsupported = fallback.unsupported_variables
                                climate_model += " + ERA5 fallback (Open-Meteo)"
                            except ValueError:
                                pass
                    elif provider == "Climate Engine":
                        climate_data, ce_metadata = fetch_climate_engine_timeseries(
                            climate_engine_key,
                            summary.gdf_wgs84,
                            start_date,
                            end_date,
                            ce_dataset_id,
                            ce_variable_ids,
                            area_reducer="mean",
                        )
                        climate_model = (
                            f"Climate Engine API · {ce_dataset_id} · {ce_variable_ids}"
                        )
                        climate_url = ce_metadata["endpoint"]
                        climate_latitude, climate_longitude = summary.centroid
                        climate_elevation = None
                        unsupported = []
                    else:
                        climate = fetch_centroid_series(
                            latitude=summary.centroid[0],
                            longitude=summary.centroid[1],
                            start_date=start_date,
                            end_date=end_date,
                            variables=variables,
                            temporal_scale=temporal_scale,
                        )
                        climate_data = climate.data
                        climate_model = climate.model
                        climate_url = climate.source_url
                        climate_latitude = climate.latitude
                        climate_longitude = climate.longitude
                        climate_elevation = climate.elevation_m
                        unsupported = climate.unsupported_variables

                    analysis_tables = {}
                    spi_table = None
                    if "SPI" in selected_analyses:
                        spi_input_data = climate_data
                        spi_source = climate_model
                        gee_ok, _ = cached_gee_status(gee_project or None)
                        if provider == "Otomatik en uygun açık kaynak" and gee_ok:
                            chirps_data = fetch_chirps_monthly_mean(
                                summary.gdf_wgs84,
                                start_date,
                                end_date,
                                project=gee_project,
                            )
                            era_rain_columns = [
                                column for column in climate_data.columns
                                if "yağış" in column.lower() and climate_data[column].dtype.kind in "fi"
                            ]
                            if era_rain_columns:
                                era_monthly = (
                                    climate_data.set_index("Tarih")[era_rain_columns[0]]
                                    .resample("MS")
                                    .sum(min_count=1)
                                    .rename("ERA5 yağış (mm)")
                                    .reset_index()
                                )
                                comparison = chirps_data[["Tarih", "Toplam yağış (mm)"]].rename(
                                    columns={"Toplam yağış (mm)": "CHIRPS yağış (mm)"}
                                ).merge(era_monthly, on="Tarih", how="outer")
                                comparison["Fark (CHIRPS - ERA5)"] = (
                                    comparison["CHIRPS yağış (mm)"] - comparison["ERA5 yağış (mm)"]
                                )
                                analysis_tables["Yağış Karşılaştırma"] = comparison
                            spi_input_data = chirps_data
                            spi_source = "CHIRPS Daily via Google Earth Engine"
                        precipitation_columns = [
                            column for column in spi_input_data.columns
                            if "yağış" in column.lower() and spi_input_data[column].dtype.kind in "fi"
                        ]
                        if not precipitation_columns:
                            available_columns = ", ".join(map(str, spi_input_data.columns))
                            raise ValueError(
                                "SPI hesaplanamadı: veri tablosunda sayısal yağış sütunu bulunamadı. "
                                f"Mevcut sütunlar: {available_columns}"
                            )
                        spi_scales = analysis_params.get("scales") or [1, 3, 6, 12]
                        spi_table = calculate_spi_table(
                            spi_input_data,
                            precipitation_columns[0],
                            spi_scales,
                        )
                        spi_table.insert(1, "SPI yağış kaynağı", spi_source)
                        analysis_tables["SPI Sonuçları"] = spi_table
                    metadata = build_metadata(
                        area={
                            "area_km2": round(summary.area_km2, 6),
                            "perimeter_km": round(summary.perimeter_km, 6),
                            "feature_count": summary.feature_count,
                            "source_crs": summary.source_crs,
                            "calculation_crs": summary.area_crs,
                            "spatial_mode": spatial_mode,
                            "spatial_statistics": spatial_stat,
                            "sampling_note": "İlk çalışan bağlayıcı alan merkezindeki ERA5-Land grid hücresini kullanır.",
                        },
                        request={
                            "provider": provider,
                            "product": climate_model,
                            "source_url": climate_url,
                            "variables": variables,
                            "unsupported_variables": unsupported,
                            "start_date": str(start_date),
                            "end_date": str(end_date),
                            "temporal_scale": temporal_scale,
                            "aggregation": aggregation,
                            "quality_control": quality_control,
                        },
                        analysis={"methods": selected_analyses, "parameters": analysis_params},
                        outputs={"formats": output_formats, "contents": include_items},
                    )
                    area_geojson = summary.gdf_wgs84.to_json(drop_id=True).encode("utf-8")
                    metadata_rows = [
                        ("Veri kaynağı", provider),
                        ("Asıl ürün", climate_model),
                        ("Kaynak URL", climate_url),
                        ("Başlangıç", start_date),
                        ("Bitiş", end_date),
                        ("Zaman çözünürlüğü", temporal_scale),
                        ("Örnekleme", "Çalışma alanı merkezindeki ERA5-Land grid hücresi"),
                        ("Enlem", climate_latitude),
                        ("Boylam", climate_longitude),
                        ("Model yüksekliği (m)", climate_elevation),
                        ("Desteklenmeyen seçimler", ", ".join(unsupported) or "Yok"),
                    ]
                    area_rows = [
                        ("Toplam alan (km²)", summary.area_km2),
                        ("Çevre (km)", summary.perimeter_km),
                        ("Coğrafi obje", summary.feature_count),
                        ("Köşe sayısı", summary.vertex_count),
                        ("Kaynak CRS", summary.source_crs),
                        ("Alan hesabı CRS", summary.area_crs),
                        ("Merkez enlem", summary.centroid[0]),
                        ("Merkez boylam", summary.centroid[1]),
                    ]
                    excel = build_excel(
                        climate_data,
                        metadata_rows=metadata_rows,
                        area_rows=area_rows,
                        analysis_tables=analysis_tables,
                    )
                    csv_data = dataframe_to_csv(climate_data)
                    graph_png = build_timeseries_png(climate_data)
                    map_png = build_area_map_png(summary.gdf_wgs84, summary.centroid)
                    gpkg = geodata_to_gpkg(summary.gdf_wgs84, summary.centroid)
                    readme = (
                        "METRİKLİM GERÇEK VERİ PAKETİ\n\n"
                        f"Kaynak: {climate_model}\n"
                        f"Dönem: {start_date} – {end_date}\n"
                        f"Kayıt sayısı: {len(climate_data):,}\n"
                        f"Örnekleme: {'Havza alan ortalaması' if provider == 'Google Earth Engine' else 'Çalışma alanının merkezindeki ERA5-Land grid hücresi'}.\n\n"
                        "DOSYALAR\n"
                        "- metriklim-iklim-verisi.xlsx: veri, kaynak, alan ve özet sayfaları\n"
                        "- metriklim-iklim-verisi.csv: CBS ve istatistik yazılımları için tablo\n"
                        "- metriklim-cbs.gpkg: çalışma alanı ve örnekleme noktası\n"
                        "- calisma-alani.geojson: çalışma alanı sınırı\n"
                        "- zaman-serisi.png: iklim grafiği\n"
                        "- calisma-alani-haritasi.png: çalışma alanı / havza sınırı\n"
                        "- [YONTEM]_[DONEM].tif: havza sınırına kırpılmış CBS raster katmanı\n"
                        "- [YONTEM]_[DONEM].png: lejantlı akademik harita önizlemesi\n"
                        "- raster-analiz-metadata.json: raster kaynağı, formül, dönem, çözünürlük ve sahne sayısı\n"
                        "- metriklim-metadata.json: veri kaynağı ve işlem izi\n"
                    ).encode("utf-8")
                    files = {
                        "metriklim-iklim-verisi.xlsx": excel,
                        "metriklim-iklim-verisi.csv": csv_data,
                        "metriklim-cbs.gpkg": gpkg,
                        "calisma-alani.geojson": area_geojson,
                        "zaman-serisi.png": graph_png,
                        "calisma-alani-haritasi.png": map_png,
                        "metriklim-metadata.json": metadata,
                        "BENI-OKU.txt": readme,
                    }
                    gee_ok, _ = cached_gee_status(gee_project or None)
                    if gee_ok:
                        if "Yağış" in variables:
                            precipitation_tif = build_climate_geotiff(
                                summary.gdf_wgs84,
                                start_date,
                                end_date,
                                "precipitation",
                                project=gee_project,
                            )
                            precipitation_name = f"yagis_toplam_{start_date}_{end_date}"
                            files[f"{precipitation_name}.tif"] = precipitation_tif
                            files[f"{precipitation_name}.png"] = build_raster_png(
                                precipitation_tif,
                                f"CHIRPS Toplam Yağış · {start_date} – {end_date}",
                                boundary=summary.gdf_wgs84,
                                palette="Blues",
                                colorbar_label="Yağış (mm)",
                                fixed_range=None,
                            )
                        if "Hava sıcaklığı" in variables:
                            temperature_tif = build_climate_geotiff(
                                summary.gdf_wgs84,
                                start_date,
                                end_date,
                                "temperature",
                                project=gee_project,
                            )
                            temperature_name = f"sicaklik_ortalama_{start_date}_{end_date}"
                            files[f"{temperature_name}.tif"] = temperature_tif
                            files[f"{temperature_name}.png"] = build_raster_png(
                                temperature_tif,
                                f"ERA5-Land Ortalama Sıcaklık · {start_date} – {end_date}",
                                boundary=summary.gdf_wgs84,
                                palette="Spectral_r",
                                colorbar_label="Sıcaklık (°C)",
                                fixed_range=None,
                            )
                    remote_methods = {
                        "NDVI", "NDWI", "NDMI", "NDBI", "EVI", "SAVI",
                        "LST", "DEM", "SLOPE", "ASPECT", "TWI",
                    }
                    remote_selected = [
                        method for method in selected_analyses if method in remote_methods
                    ]
                    remote_metadata = []
                    remote_errors = []
                    raster_styles = {
                        "NDVI": ("YlGn", "NDVI", (-1.0, 1.0)),
                        "NDWI": ("Blues", "NDWI", (-1.0, 1.0)),
                        "NDMI": ("BrBG", "NDMI", (-1.0, 1.0)),
                        "NDBI": ("magma", "NDBI", (-1.0, 1.0)),
                        "EVI": ("YlGn", "EVI", (-1.0, 1.0)),
                        "SAVI": ("summer", "SAVI", (-1.0, 1.0)),
                        "LST": ("inferno", "Yüzey sıcaklığı (°C)", None),
                        "DEM": ("terrain", "Yükselti (m)", None),
                        "SLOPE": ("YlOrBr", "Eğim (°)", (0.0, 60.0)),
                        "ASPECT": ("hsv", "Bakı (°)", (0.0, 360.0)),
                        "TWI": ("viridis", "TWI", None),
                    }
                    for method in remote_selected:
                        try:
                            raster_tif, method_metadata = build_remote_analysis_geotiff(
                                summary.gdf_wgs84,
                                start_date,
                                end_date,
                                method,
                                project=gee_project or None,
                                cloud_limit=int(analysis_params.get("cloud_limit", 30)),
                            )
                            base_name = (
                                f"{method}_{start_date}_{end_date}"
                                if method in {"NDVI", "NDWI", "NDMI", "NDBI", "EVI", "SAVI", "LST"}
                                else f"{method}_statik"
                            )
                            palette, colorbar_label, fixed_range = raster_styles[method]
                            files[f"{base_name}.tif"] = raster_tif
                            files[f"{base_name}.png"] = build_raster_png(
                                raster_tif,
                                f"{method} · {ANALYSIS_METHODS[method]['title']}",
                                boundary=summary.gdf_wgs84,
                                palette=palette,
                                colorbar_label=colorbar_label,
                                fixed_range=fixed_range,
                            )
                            remote_metadata.append(method_metadata)
                        except Exception as method_error:
                            remote_errors.append(f"{method}: {method_error}")
                    if remote_metadata:
                        files["raster-analiz-metadata.json"] = json.dumps(
                            remote_metadata,
                            ensure_ascii=False,
                            indent=2,
                            default=str,
                        ).encode("utf-8")
                    if remote_errors:
                        files["analiz-uyarilari.txt"] = (
                            "Üretilemeyen analizler\n\n" + "\n".join(remote_errors)
                        ).encode("utf-8")
                    if spi_table is not None:
                        files["spi-sonuclari.csv"] = dataframe_to_csv(spi_table)
                        gee_ok, _ = cached_gee_status(gee_project or None)
                        if gee_ok:
                            for selected_scale in (analysis_params.get("scales") or [3]):
                                selected_scale = int(selected_scale)
                                spi_tif = build_chirps_spi_geotiff(
                                    summary.gdf_wgs84,
                                    end_date,
                                    selected_scale,
                                    project=gee_project,
                                )
                                files[f"SPI-{selected_scale}_{end_date:%Y-%m}.tif"] = spi_tif
                                files[f"SPI-{selected_scale}_{end_date:%Y-%m}.png"] = build_raster_png(
                                    spi_tif,
                                    f"CHIRPS SPI-{selected_scale} · {end_date:%Y-%m}",
                                    boundary=summary.gdf_wgs84,
                                )
                    st.session_state.output_files = files
                    st.session_state.output_package = build_complete_package(files)
                    st.session_state.output_metadata = metadata
                    st.session_state.output_data = climate_data
                    st.session_state.output_source = climate_model
                    st.session_state.output_analysis_errors = remote_errors
                st.success(
                    f"Gerçek iklim verisi indirildi: {len(climate_data):,} kayıt. "
                    "Excel, CSV, grafik, harita ve CBS paketi hazır."
                )
                if unsupported:
                    st.warning(
                        "Bu bağlayıcıda desteklenmeyen değişkenler pakete eklenmedi: "
                        + ", ".join(unsupported)
                    )
                if st.session_state.get("output_analysis_errors"):
                    st.warning(
                        "Bazı rasterlar üretilemedi; diğer doğrulanmış çıktılar korundu:\n\n"
                        + "\n".join(
                            f"- {item}"
                            for item in st.session_state.output_analysis_errors
                        )
                    )
            except Exception as exc:
                st.error(f"Veri indirme veya çıktı oluşturma başarısız: {exc}")

    if st.session_state.get("output_package"):
        st.info(
            f"Kaynak: {st.session_state.get('output_source', '—')} · "
            f"Kayıt: {len(st.session_state.get('output_data', [])):,} · "
            "İndirme hedefi: tarayıcınızın İndirilenler klasörü"
        )
        d1, d2, d3 = st.columns(3)
        d1.download_button(
            "Tüm paketi indir (ZIP)",
            st.session_state.output_package,
            file_name="metriklim-gercek-veri-paketi.zip",
            mime="application/zip",
            use_container_width=True,
        )
        d2.download_button(
            "Excel indir",
            st.session_state.output_files["metriklim-iklim-verisi.xlsx"],
            file_name="metriklim-iklim-verisi.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        d3.download_button(
            "CSV indir",
            st.session_state.output_files["metriklim-iklim-verisi.csv"],
            file_name="metriklim-iklim-verisi.csv",
            mime="text/csv",
            use_container_width=True,
        )
        cbs1, cbs2, cbs3 = st.columns(3)
        cbs1.download_button(
            "GeoPackage indir",
            st.session_state.output_files["metriklim-cbs.gpkg"],
            file_name="metriklim-cbs.gpkg",
            mime="application/geopackage+sqlite3",
            use_container_width=True,
        )
        cbs2.download_button(
            "Zaman serisi grafiği",
            st.session_state.output_files["zaman-serisi.png"],
            file_name="zaman-serisi.png",
            mime="image/png",
            use_container_width=True,
        )
        cbs3.download_button(
            "Alan haritası",
            st.session_state.output_files["calisma-alani-haritasi.png"],
            file_name="calisma-alani-haritasi.png",
            mime="image/png",
            use_container_width=True,
        )
        raster_names = [name for name in st.session_state.output_files if name.lower().endswith(".tif")]
        if raster_names:
            st.subheader("CBS raster katmanları")
            raster_columns = st.columns(min(3, len(raster_names)))
            for index, raster_name in enumerate(raster_names):
                label = (
                    "Yağış GeoTIFF"
                    if raster_name.startswith("yagis_")
                    else "Sıcaklık GeoTIFF"
                    if raster_name.startswith("sicaklik_")
                    else f"{raster_name.split('_')[0]} GeoTIFF"
                )
                raster_columns[index % len(raster_columns)].download_button(
                    label,
                    st.session_state.output_files[raster_name],
                    file_name=raster_name,
                    mime="image/tiff",
                    use_container_width=True,
                    key=f"raster_download_{index}_{raster_name}",
                )
        preview_names = [
            name
            for name in st.session_state.output_files
            if name.lower().endswith(".png")
            and name not in {"zaman-serisi.png", "calisma-alani-haritasi.png"}
        ]
        if preview_names:
            with st.expander("Üretilen iklim, indis ve topoğrafya haritalarını önizle", expanded=True):
                preview_columns = st.columns(min(2, len(preview_names)))
                for index, preview_name in enumerate(preview_names):
                    preview_columns[index % len(preview_columns)].image(
                        st.session_state.output_files[preview_name],
                        caption=preview_name.replace("_", " ").replace(".png", ""),
                        width="stretch",
                    )
        with st.expander("İndirilecek veriyi önizle", expanded=True):
            st.dataframe(st.session_state.output_data.head(500), width="stretch", hide_index=True)
            st.caption("Önizleme ilk 500 kaydı gösterir; indirilen Excel ve CSV tüm kayıtları içerir.")

