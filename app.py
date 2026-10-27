"""Streamlit multipage app: reinforced concrete member design.

Run:  streamlit run app.py
"""
import streamlit as st

# Keep widget values when switching pages: Streamlit drops the state of widgets
# that are not rendered, so re-assign them as plain session state.
for _k in list(st.session_state.keys()):
    if _k.startswith(("bm_", "_bm_", "cb_")) and "_ed_" not in _k or _k in {
        "shape", "b", "h", "D", "cover", "fc", "fy", "fyt", "agg", "bar", "nx", "ny", "n_circ",
        "transverse", "tie", "s", "legs_x", "legs_y", "sway", "lu_x", "lu_y", "k_x", "k_y",
        "m1m2_x", "m1m2_y", "beta_dns", "ds_x", "ds_y", "trans_load", "unit_mat", "unit_force",
    }:
        st.session_state[_k] = st.session_state[_k]

pg = st.navigation([
    st.Page("beam_app.py", title="ออกแบบคาน คสล.", icon="🏗️", default=True),
    st.Page("continuous_beam_app.py", title="คานต่อเนื่อง (Singly/Doubly)", icon="📐"),
    st.Page("column_app.py", title="ออกแบบเสา คสล.", icon="🏛️"),
])
pg.run()
