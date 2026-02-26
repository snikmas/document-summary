import streamlit as st
import time
import json
import requests

st.set_page_config(
    page_title="DocPipeline",
    page_icon=":material/description:",
    layout="centered"
)

API_URL = 'http://localhost:8000'
SUPPORTED_TYPES = ['pdf', 'docx', 'txt', 'html', 'csv']

# 1. init state
if 'job_id' not in st.session_state:
    st.session_state.job_id = None


# 2. ui
st.title("Document Intelligence Pipeline")
st.caption("Upload any document — PDF, DOCX, TXT, HTML, or CSV — and get an instant AI-powered summary.")

# U4: restrict uploader to supported types
uploaded_file = st.file_uploader("Upload your file", type=SUPPORTED_TYPES)

# U8: file info preview after selection
if uploaded_file is not None and st.session_state.job_id is None:
    file_size = uploaded_file.size
    if file_size < 1024:
        size_str = f"{file_size} B"
    elif file_size < 1024 * 1024:
        size_str = f"{file_size / 1024:.1f} KB"
    else:
        size_str = f"{file_size / (1024 * 1024):.1f} MB"

    ext = uploaded_file.name.rsplit('.', 1)[-1].upper() if '.' in uploaded_file.name else 'Unknown'
    st.info(f"**{uploaded_file.name}** — {ext} file, {size_str}")

# 3. handle upload
if uploaded_file is not None and st.session_state.job_id is None:
    filename = uploaded_file.name
    file_bytes = uploaded_file.read()
    content_type = uploaded_file.type


    try:
        with st.spinner("Uploading file..."):
            res = requests.post(
                f'{API_URL}/process',
                files={'file': (filename, file_bytes, content_type)}
            )
            res.raise_for_status()
        st.session_state.job_id = res.json()['job_id']
        st.rerun()
    except requests.exceptions.ConnectionError:
        st.error("Cannot reach the server. Make sure the backend is running.")
    except requests.exceptions.RequestException as e:
        st.error(f"Upload failed: {e}")


# 4. poll if job is running
if st.session_state.job_id:
    try:
        response = requests.get(f'{API_URL}/jobs/{st.session_state.job_id}')
        response.raise_for_status()
        status_data = response.json()
        status = status_data['status']
    except requests.exceptions.RequestException:
        st.error("Cannot reach the server. Make sure the backend is running.")
        st.stop()

    st.divider()

    if status == 'done':
        st.success("Analysis complete!")

        result = requests.get(f'{API_URL}/jobs/{st.session_state.job_id}/result').json()

        col1, col2 = st.columns(2)
        col1.metric("Language", result.get('language', 'N/A'))
        col2.metric("Word Count", result.get('word_count', 'N/A'))

        st.subheader("Summary")
        st.markdown(result['summary'])

        st.subheader("Key Points")
        points_md = '\n'.join(f"- {point}" for point in result['key_points'])
        st.markdown(points_md)

        st.divider()
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            summary_text = f"Summary\n{'=' * 40}\n{result['summary']}\n\nKey Points\n{'=' * 40}\n"
            summary_text += '\n'.join(f"- {p}" for p in result['key_points'])
            summary_text += f"\n\nLanguage: {result.get('language', 'N/A')}"
            summary_text += f"\nWord Count: {result.get('word_count', 'N/A')}"
            st.download_button(
                label="Download as TXT",
                data=summary_text,
                file_name="summary.txt",
                mime="text/plain"
            )
        with dl_col2:
            st.download_button(
                label="Download as JSON",
                data=json.dumps(result, indent=2, ensure_ascii=False),
                file_name="summary.json",
                mime="application/json"
            )

        st.divider()
        if st.button("Process another file"):
            st.session_state.job_id = None
            st.rerun()

    elif status == 'processing' or status == 'pending':
        if status == 'pending':
            msg = "Queued, waiting to start..."
        else:
            msg = "Analyzing your document..."
        with st.spinner(msg):
            time.sleep(2)
        st.rerun()

    elif status == 'failed':
        error_detail = status_data.get('error', '')
        if error_detail:
            st.error(f"Processing failed: {error_detail}")
        else:
            st.error("Processing failed. The file may be unsupported or corrupted.")

        if st.button("Try another file"):
            st.session_state.job_id = None
            st.rerun()
