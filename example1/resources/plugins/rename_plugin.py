import os
import pandas
import logging
import shutil

from tools import tools 
from bidsMeta import BIDSfieldLibrary
from bids import BidsSession

from definitions import Series, checkSeries

logger = logging.getLogger(__name__)

# global variables
rawfolder = ""
bidsfolder = ""
dry_run = False


resources = os.path.join(os.path.dirname(__file__), "..")

df_subjects = None
scans_map = {}

# scale to convert ms in log-files to seconds
time_scale = 1e-3

# list of subjects exel-file columns 
excel_col_list = {'Patient' : 'pat',
                  'S_A_E' : "pat_sae",
                  1: "pat_1", 2: "pat_2", 3: "pat_3",
                  'Control' : "cnt",
                  'S_A_E.1': "cnt_sae",
                  '1.1': "cnt_1", '2.1': "cnt_2", '3.1': "cnt_3",
                  }

# sub_columns = BIDSfieldLibrary()


def InitEP(source: str, destination: str,
           dry: bool,
           subjects: str="") -> int:
    global rawfolder
    global bidsfolder
    global dry_run
    global subject_file

    rawfolder = source
    bidsfolder = destination
    dry_run = dry
    if subjects:
        subject_file = subjects
    else:
        subject_file = os.path.join(resources, "Appariement.xlsx")
    logger.info(subject_file)

    if not os.path.isfile(subject_file):
        raise FileNotFoundError("Subject file '{}' not found"
                                .format(subject_file))

    # creating df for subjects
    global df_subjects
    df_subjects = pandas.read_excel(subject_file,
                                    sheet_name=0, header=0,
                                    usecols=[0,1,2,3,4,5,6,7,8,9,10])
    df_subjects.rename(index=str, columns=excel_col_list,inplace=True)
    df_subjects = df_subjects[df_subjects['pat'].notnull()
                              | df_subjects['cnt'].notnull()]


def SubjectEP(session: BidsSession) -> int:
    sub_id = int(session.subject)
    index = df_subjects.loc[df_subjects["pat"] == sub_id].index 
    status = 0
    prefix = "pat"
    if len(index) == 0:
        # Subject not in patient list, looking in control
        index = df_subjects.loc[df_subjects["cnt"] == sub_id].index
        if len(index) == 0:
            raise KeyError("Subject {} not found in table"
                           .format(sub_id))
        status = 1
        prefix = "cnt"
    index = index[0]

    # retrieving demographics
    # <sex>_<age>_<education>
    line = df_subjects.loc[index, prefix + "_sae"].split("_")
    sex = line[0]
    age = int(line[1])
    education = int(line[2])
    session.sub_values["participant_id"] = "sub-" + session.subject
    session.sub_values["sex"] = sex
    session.sub_values["age"] = age
    session.sub_values["education"] = education

    # looking for pairing
    if status == 0:
        session.sub_values["group"] = "patient"
        session.sub_values["paired"] = "sub-{:03}".format(int(df_subjects
                                                  .loc[index, "cnt"]))
    else:
        session.sub_values["group"] = "control"
        session.sub_values["paired"] = "sub-{:03}".format(int(df_subjects
                                                  .loc[index, "pat"]))

    # looking for order of sessions
    global scans_map
    scans_map = {}
    scans_order = sorted([os.path.basename(s) for s in
                          tools.lsdirs(os.path.join(rawfolder,
                                                    session.subject),
                                       "s*")
                          ])
    for ind, s in enumerate(("_1", "_2", "_3")):
        v = "ses-" + str(df_subjects.loc[index, prefix + s]).strip()
        ses = "ses" + s
        if v == "ses-nan":
            session.sub_values[ses] = ""
            logger.warning("Subject {}({}): missing {} value"
                           .format(session.sub_values["participant_id"],
                                   session.sub_values["group"],
                                   ses)
                           )
        elif v not in Series:
            logger.critical("Subject {}({}): Invalid {}: {}"
                            .format(session.sub_values["participant_id"],
                                    session.sub_values["group"],
                                    ses,
                                    session.sub_values[ses])
                            )
            raise KeyError("Invalid {}: {}"
                           .format(ses, v))
        else:
            session.sub_values[ses] = v
            scans_map[scans_order[ind]] = session.sub_values[ses]

    # checking if all scans are identifyable
    for scan in scans_order:
        if scan not in scans_map:
            logger.error("Subject {}({}): Can't identify session {}"
                         .format(session.sub_values["participant_id"],
                                 session.sub_values["group"],
                                 scan))
            scans_map[scan] = scan

    session.subject = "sub-" + session.subject
    return 0


def SessionEP(session: BidsSession) -> int:
    # retrieving correct session name
    session.session = scans_map[session.session]
    return 0


def SessionEndEP(session: BidsSession):
    path = os.path.join(bidsfolder,
                        session.getPath(True))
    out_path = os.path.join(path,
                            "MRI")
    if not checkSeries(out_path,
                       session.subject, session.session,
                       False):
        return 1

    # parcing log files
    if session.session == "ses-STROOP":
        return 0

    logs = os.path.join(session.in_path, "inp")
    aux_d = os.path.join(path, "aux")
    if not os.path.isdir(logs):
        raise NotADirectoryError(logs)

    os.makedirs(aux_d, exist_ok=True)
    for file in ("FCsepNBack.tsv", "VAS.tsv"):
        file = os.path.join(logs, file)
        if not os.path.isfile(file):
            raise FileNotFoundError(file)
        shutil.copy2(file, aux_d)

    for file in ("FCsepNBack.json", "VAS.json"):
        file = os.path.join(resources, file)
        if not os.path.isfile(file):
            raise FileNotFoundError(file)
        shutil.copy2(file, aux_d)

    return 0
