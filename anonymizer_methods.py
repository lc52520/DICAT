import os
import sys
import xml.etree.ElementTree as ET
import subprocess
import re
import shutil
from shutil import move

"""
Test whether PyDICOM module exists and import it.
Notes:
  - in the past, PyDICOM was imported using "import pydicom as dicom"
  - newer versions of the PyDICOM module are imported using "import dicom"
  - returns true if the PyDICOM was imported, false otherwise
"""
# create a boolean variable that returns True if PyDICOM was imported, False if not
use_pydicom = False
try:
    import pydicom as dicom

    use_pydicom = True  # set use_pydicom to true as PyDICOM was found and imported
except ImportError:
    try:  # try importing newer versions of PyDICOM
        import dicom

        use_pydicom = True  # set use_pydicom to true as PyDICOM was found and imported
    except ImportError:
        use_pydicom = False  # set use_pydicom to false as PyDICOM was not found


def find_anonymizer_tool():
    """
    Determine which anonymizer tool will be used by the program:
    - PyDICOM python module if found and imported
    - DICOM toolkit if found on the filesystem

    :param: None

    :return: tool to use for DICOM anonymization
     :rtype: object

    """

    if use_pydicom:
        return 'PyDICOM'  # PyDICOM will be used and returned if PyDICOM was found
    elif test_executable('dcmdump'):
        return 'DICOM_toolkit'  # DICOM toolkit will be used if dcmdump executable exists
    else:
        return False  # Return False if no tool was found to read and anonymize DICOMs


def test_executable(executable):
    """
    Test if an executable exists.
    Returns True if executable exists, False if not found.

    :param executable: executable to test
     :type executable: str

    :return: return True if executable was found, False otherwise
     :rtype: bool

    """
    # TODO: find a way to not display dcmdump help in the terminal

    try:  # try running the executable
        subprocess.call([executable])
        return True
    except OSError:
        return False


def GrepDicomsFromFolder(dicom_folder):
    """
    Grep recursively all DICOMs from folder

    :param dicom_folder: folder to look for DICOMs
     :type dicom_folder: str

    :returns:
      dicoms_list  -> list of DICOMs (with full path)
      subdirs_list -> list of subdirectories (with full path)
     :rtype: list

    """

    # Initialize list of DICOMs and subdirectories
    dicoms_list = []
    subdirs_list = []
    # Grep DICOM files recursively and insert them in dicoms_list
    # Same for subdirectories
    # Regular expression to identify files that are not DICOM.
    pattern = re.compile("\.bmp$|\.png$|\.zip$|\.txt$|\.jpeg$|\.pdf$|\.DS_Store")
    for root, subdirs, files in os.walk(dicom_folder, topdown=True):
        if len(files) != 0 or len(subdirs) != 0:
            for dicom_file in files:
                if pattern.search(dicom_file) is None:
                    dicoms_list.append(os.path.join(root, dicom_file))
            for subdir in subdirs:
                subdirs_list.append(subdir)
        else:
            sys.exit('Could not find any files in ' + dicom_folder)

    return dicoms_list, subdirs_list


def Grep_DICOM_fields(xml_file):
    """
    Read DICOM fields from XML file called "fields_to_zap.xml"

    :param xml_file: XML file to read
     :type xml_file: str

    :return: dicom_fields -> dictionary of DICOM fields
     :rtype: dict
    """

    xmldoc = ET.parse(xml_file)
    dicom_fields = {}
    for item in xmldoc.findall('item'):
        name = item.find('name').text
        description = item.find('description').text
        editable = True if (item.find('editable').text == "yes") else False  # kr#
        dicom_fields[name] = {"Description": description, "Editable": editable}  # kr#
        # dicom_fields[name] = {"Description": description}

    return dicom_fields


def Grep_DICOM_values_PyDicom(dicom_folder, dicom_fields):
    """
    Grep value from DICOM fields using PyDICOM.

    :param dicom_folder: folder with DICOMs
     :type dicom_folder: str
    :param dicom_fields: dictionary of DICOM fields
     :type dicom_fields: dict

    :return: updated dictionary of DICOM fields with DICOM values
     :rtype: dict

    """

    # Grep first DICOM of the directory
    # TODO: Need to check if file is DICOM though, otherwise go to next one
    (dicoms_list, subdirs_list) = GrepDicomsFromFolder(dicom_folder)
    dicom_file = dicoms_list[0]

    # Read DICOM file using PyDICOM
    dicom_dataset = dicom.read_file(dicom_file)

    # Grep information from DICOM header and store them
    # into dicom_fields dictionary under flag Value
    # Dictionnary of DICOM values to be returned
    for name in dicom_fields:
        try:
            dicom_fields[name]['Value'] = dicom_dataset.data_element(dicom_fields[name]['Description']).value
        except:
            continue

    return dicom_fields


def Grep_DICOM_values(dicom_folder, dicom_fields):
    """
    Grep value from DICOM fields using dcmdump from the DICOM toolkit

    :param dicom_folder: folder with DICOMs
     :type dicom_folder: str
    :param dicom_fields: dictionary of DICOM fields
     :type dicom_fields: dict

    :return: updated dictionary of DICOM fields with DICOM values for those fields
     :rtype: dict

    """

    # Grep first DICOM of the directory
    # TODO: Need to check if file is DICOM though, otherwise go to next one
    (dicoms_list, subdirs_list) = GrepDicomsFromFolder(dicom_folder)
    dicom_file = dicoms_list[0]

    # Grep information from DICOM header and store them
    # into dicom_fields dictionary under flag Value
    for name in dicom_fields:
        dump_cmd = "dcmdump -ml +P " + name + " -q " + dicom_file
        result = subprocess.check_output(dump_cmd, shell=True)
        tmp_val = re.match(".+\[(.+)\].+", result)
        if tmp_val:
            value = tmp_val.group(1)
            dicom_fields[name]['Value'] = value

    return dicom_fields


def Dicom_zapping_PyDicom(dicom_folder, dicom_fields):
    """
    Run dcmodify on all fields to zap using PyDICOM recursive wrapper

    :param dicom_folder: folder with DICOMs
     :type dicom_folder: str
    :param dicom_fields: dictionary of DICOM fields and values
     :type dicom_fields: dict

    :returns:
      anonymize_zip -> path to the zip file of the anonymized DICOMs
      original_zip  -> path to the zip file of the original DICOMs
     :rtype: str

    """

    # Grep all DICOMs present in directory
    (dicoms_list, subdirs_list) = GrepDicomsFromFolder(dicom_folder)

    # Create an original_dcm and anonymized_dcm directory in the DICOM folder, as well as subdirectories
    (original_dir, anonymize_dir) = createDirectories(dicom_folder, dicom_fields, subdirs_list)

    # Move DICOMs into the original_directory created and copy DICOMs into the anonymized_folder
    for dicom in dicoms_list:
        shutil.copy(dicom, anonymize_dir)
        move(dicom, original_dir)

    # Zap DICOMs recursively
    for dicom in dicoms_list:
        anonymize_dcm = dicom.replace(dicom_folder, anonymize_dir)
        if len(dicom) != 0:
            actual_PyDICOM_zapping(os.path.join(anonymize_dcm), dicom_fields)

    # Zip the anonymize and original DICOM folders
    (anonymize_zip, original_zip) = zip_DICOM_directories(anonymize_dir, original_dir, subdirs_list)

    # return zip files
    return anonymize_zip, original_zip


def actual_PyDICOM_zapping(dicom_file, dicom_fields):
    """
    Actual zapping method for PyDICOM

    :param dicom_file: DICOM to anonymize
     :type dicom_file: str
    :param dicom_fields: Dictionary with DICOM fields and values to use to anonymize
     :type dicom_fields: dict

    :return: None

    """

    dicom_dataset = dicom.read_file(dicom_file)

    for name in dicom_fields:
        new_val = ""
        if 'Value' in dicom_fields[name]:
            new_val = dicom_fields[name]['Value']

        if dicom_fields[name]['Editable'] is True:
            try:
                dicom_dataset.data_element(dicom_fields[name]['Description']).value = new_val
            except:
                continue
        else:
            try:
                dicom_dataset.data_element(dicom_fields[name]['Description']).value = ''
            except:
                continue
    dicom_dataset.save_as(dicom_file)


def zip_DICOM_directories(anonymize_dir, original_dir, subdirs_list):
    """
    Zip the anonymize and origin DICOM directories.

    :param anonymize_dir: directory with the anonymized DICOM files
     :type anonymize_dir: str
    :param original_dir: directory with the original DICOM files
     :type original_dir: str
    :param subdirs_list: list of subdirectories within the DICOM directories
     :type subdirs_list: list

    :returns:
      anonymize_zip -> path to the zip file of the anonymized DICOM files
      original_zip  -> path to the zip file of the original DICOM files
     :rtype: str

    """


    # If anonymize and original folders exist, zip them
    if os.path.exists(anonymize_dir) and os.path.exists(original_dir):
        original_zip = zipDicom(original_dir)
        anonymize_zip = zipDicom(anonymize_dir)
    else:
        sys.exit('Failed to find original and anonymize data folders')

    # If archive anonymized and original DICOMs found, remove subdirectories in root directory
    if os.path.exists(anonymize_zip) and os.path.exists(original_zip):
        for subdir in subdirs_list:
            shutil.rmtree(dicom_folder + os.path.sep + subdir)
    else:
        sys.exit('Failed: could not zip anonymize and original data folders')

    # Return zip files
    return anonymize_zip, original_zip


def Dicom_zapping(dicom_folder, dicom_fields):
    """
    Run dcmodify on all DICOM fields to zap.

    :param dicom_folder: folder with DICOMs
     :type dicom_folder: str
    :param dicom_fields: dictionary of DICOM fields and values
     :type dicom_fields: dict

    :returns:
      original_zip  -> Path to the zip file containing original DICOM files
      anonymize_zip -> Path to the zip file containing anonymized DICOM files
     :rtype: str

    """

    # Grep all DICOMs present in directory
    (dicoms_list, subdirs_list) = GrepDicomsFromFolder(dicom_folder)

    # Create an original_dcm and anonymized_dcm directory in the DICOM folder, as well as subdirectories
    (original_dir, anonymize_dir) = createDirectories(dicom_folder, dicom_fields, subdirs_list)

    # Initialize the dcmodify command
    modify_cmd = "dcmodify "
    changed_fields_nb = 0
    for name in dicom_fields:
        # Grep the new values
        new_val = ""
        if 'Value' in dicom_fields[name]:
            new_val = dicom_fields[name]['Value']

        # Run dcmodify if update is set to True
        if not dicom_fields[name]['Editable'] and 'Value' in dicom_fields[name]:
            modify_cmd += " -ma \"(" + name + ")\"=\" \" "
            changed_fields_nb += 1
        else:
            if dicom_fields[name]['Update'] == True:
                modify_cmd += " -ma \"(" + name + ")\"=\"" + new_val + "\" "
                changed_fields_nb += 1

    # Loop through DICOMs and
    # 1. move DICOM files into anonymized_dir (we'll move the .bak file into original_dcm once dcmodify has been run)
    # 2. run dcmodify
    # 3. move .bak file into original directory
    for dicom in dicoms_list:
        original_dcm = dicom.replace(dicom_folder, original_dir)
        anonymize_dcm = dicom.replace(dicom_folder, anonymize_dir)
        orig_bak_dcm = anonymize_dcm + ".bak"
        if changed_fields_nb > 0:
            move(dicom, anonymize_dcm)
            subprocess.call(modify_cmd + anonymize_dcm, shell=True)
            if os.path.exists(orig_bak_dcm):
                move(orig_bak_dcm, original_dcm)
        else:
            move(dicom, original_dcm)

    # If anonymize and original folders exist, zip them
    if os.path.exists(anonymize_dir) and os.path.exists(original_dir):
        original_zip = zipDicom(original_dir)
        anonymize_zip = zipDicom(anonymize_dir)
    else:
        sys.exit('Failed to anonymize data')

    # If archive anonymized and original DICOMs found, remove subdirectories in root directory
    if os.path.exists(anonymize_zip) and os.path.exists(original_zip):
        for subdir in subdirs_list:
            shutil.rmtree(dicom_folder + os.path.sep + subdir)

    return original_zip, anonymize_zip


def createDirectories(dicom_folder, dicom_fields, subdirs_list):
    """
    Create two directories in the main DICOM folder:
        - one to copy over the original DICOM sub-folders and files
        - one for the anonymized DICOM dataset

    :param dicom_folder: path to the folder containing the DICOM dataset
     :type dicom_folder: str
    :param dicom_fields: dictionary of DICOM fields and values
     :type dicom_fields: dict
    :param subdirs_list: list of subdirectories found in dicom_folder
     :type subdirs_list: list

    :returns:
      original_dir  -> directory containing original DICOM dataset
      anonymize_dir -> directory containing anonymized DICOM dataset
     :rtype: str

    """

    # Create an original_dcm and anonymized_dcm directory in the DICOM folder, as well as subdirectories
    original_dir = dicom_folder + os.path.sep + dicom_fields['0010,0010']['Value']
    anonymize_dir = dicom_folder + os.path.sep + dicom_fields['0010,0010']['Value'] + "_anonymized"
    os.mkdir(original_dir, 0755)
    os.mkdir(anonymize_dir, 0755)
    # Create subdirectories in original and anonymize directory, as found in DICOM folder
    for subdir in subdirs_list:
        os.mkdir(original_dir + os.path.sep + subdir, 0755)
        os.mkdir(anonymize_dir + os.path.sep + subdir, 0755)

    return original_dir, anonymize_dir


def zipDicom(directory):
    """
    Function that zip a directory.

    :param directory: path to the directory to zip
     :type directory: str

    :return: archive -> path to the created zip file
     :rtype: str

    """

    archive = directory + '.zip'

    if (os.listdir(directory) == []):
        sys.exit("The directory " + directory + " is empty and will not be archived.")
    else:
        shutil.make_archive(directory, 'zip', directory)

    if (os.path.exists(archive)):
        shutil.rmtree(directory)
        return archive
    else:
        sys.exit(archive + " could not be created.")
