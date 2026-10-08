import requests
import streamlit as st

st.set_page_config(page_title="API Change Guard", page_icon="🛡️")
st.title("API Change Guard")
st.write("Compare two OpenAPI YAML files and review compatibility risks.")

api_url = st.sidebar.text_input(
    "API base URL", value="http://127.0.0.1:8000"
).rstrip("/")
api_v1 = st.file_uploader("API v1 (older)", type=["yaml", "yml"])
api_v2 = st.file_uploader("API v2 (newer)", type=["yaml", "yml"])

if st.button("Analyze changes", type="primary"):
    if api_v1 is None or api_v2 is None:
        st.error("Upload both API versions before analyzing.")
        st.stop()

    try:
        response = requests.post(
            f"{api_url}/analyze",
            json={
                "api_v1": api_v1.getvalue().decode("utf-8-sig"),
                "api_v2": api_v2.getvalue().decode("utf-8-sig"),
            },
            timeout=130,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        detail = exc
        if exc.response is not None:
            try:
                error_body = exc.response.json()
                if isinstance(error_body, dict):
                    detail = error_body.get("detail", exc)
            except ValueError:
                detail = exc.response.text or exc
        st.error(f"Analysis failed: {detail}")
        st.stop()

    result = response.json()
    st.subheader("Detected changes")
    if result["changes"]:
        st.dataframe(result["changes"], use_container_width=True, hide_index=True)
    else:
        st.info("No supported changes detected.")

    report = result["risk_report"]
    st.subheader(f"Risk: {report['risk']}")
    st.metric("Breaking change", "Yes" if report["breaking"] else "No")
    st.metric("Confidence", f"{report['confidence']:.0%}")
    st.write("**Reason**")
    st.write(report["reason"])
    st.write("**Affected consumers**")
    st.write(", ".join(report["affected_consumers"]) or "None identified")
    st.write("**Recommended action**")
    st.write(report["recommended_action"])
    if report["human_review_required"]:
        st.warning("Human review is required.")
