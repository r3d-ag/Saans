# Saans methodology and release limits

## CPCB National AQI

The current method is `cpcb-naqi-2014-v1`. Its versioned categories, pollutant breakpoints, units, averaging windows and validity settings are stored in [`core/aqi/data/cpcb-naqi-2014-v1.json`](../core/aqi/data/cpcb-naqi-2014-v1.json), returned by `GET /v1/method`, and recorded on every stored AQI snapshot.

For pollutant concentration `Cp` in breakpoint band `[BPlo, BPhi]`, the sub-index is linearly interpolated:

```text
Ip = Ilo + (Cp - BPlo) * (Ihi - Ilo) / (BPhi - BPlo)
```

The station AQI is the maximum valid pollutant sub-index. The pollutant with that value is shown as dominant. Saans requires three valid pollutant sub-indices, including PM2.5 or PM10. The calculation requires 16 of 24 hourly observations for 24-hour pollutants. For CO and O3, this project accepts 6 of 8 observations for the 8-hour mean; this is a documented project choice. Above the last concentration band, the final band's slope is extended and capped at AQI 500.

## Data and quality

- **OpenAQ v3:** station locations and latest pollutant observations. Values are converted to the method's standard units and upserted by station, pollutant and source timestamp.
- **Open-Meteo:** hourly weather observations/forecast context stored for analysis. Weather is not currently used as a model feature.
- **NASA FIRMS:** active-fire detections stored with observation time and coordinates. Satellite detections are sparse and do not prove that a fire caused a local AQI change.
- **CPCB:** the standard and breakpoints inform the calculation. Saans does not automatically ingest CPCB's published station AQI for its validation set.

Range, spike, persistence and unit checks are applied during ingestion. An unconfirmed spike is retained with a quality flag, not presented as confirmed evidence. No automatic interpolation is performed. Trust summarizes freshness, completeness, quality flags and available nearby-station agreement; it is a data-quality indicator, not a probability that the AQI is correct.

## Forecast and attribution

The shipped forecast is a persistence baseline at 24 and 48 hours. Its indicative interval and category distribution are derived from recent variation; they are not calibrated probabilities or a claim of forecast skill. A time-ordered LightGBM training and evaluation pipeline is included. It uses lagged AQI and calendar features, compares candidates with persistence, and publishes only models that pass its evaluation gates. Weather and fire predictors are excluded until archived issue-time features are available. A trained model is optional; the service safely falls back to persistence.

Cause labels are transparent rules based on available readings, season and evidence. They are heuristics, not source apportionment. SHAP explanations are not currently emitted by the service.

## Validation status and limitations

This release includes an AQI calculation test suite and a keyless demo dataset for local preview. Demo readings are illustrative and must not be used as measurements or validation data. No live CPCB comparison result or held-out-season forecast score is bundled. Collect and review a labelled CPCB sample before making those performance claims.

Station coverage depends on the configured OpenAQ results. Rural interpolation is uncertain, provider data may be delayed, and FIRMS can miss short-lived events between satellite overpasses. The application is educational, not medical advice or an official CPCB reporting system. Low-cost sensor correction and sensor co-location are not implemented.

## Attribution and reuse

The CPCB National AQI method is attributed to the Central Pollution Control Board. OpenAQ, Open-Meteo and NASA FIRMS are identified in the API method response. Check the terms and attribution requirements that apply to the specific source records before redistributing exports. The application code is MIT-licensed; that license does not grant rights to third-party data.
