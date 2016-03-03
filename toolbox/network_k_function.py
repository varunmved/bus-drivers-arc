import arcpy
import os
import network_k_calculation
import odcm_distance_calculation
import network_length_calculation

from collections import OrderedDict
from arcpy       import env

# ArcMap caching prevention.
network_k_calculation      = reload(network_k_calculation)
odcm_distance_calculation  = reload(odcm_distance_calculation)
network_length_calculation = reload(network_length_calculation)

from network_k_calculation      import NetworkKCalculation
from odcm_distance_calculation  import ODCMDistanceCalculation
from network_length_calculation import NetworkLengthCalculation

class NetworkKFunction(object):
  ###
  # Initialize the tool.
  ###
  def __init__(self):
    self.label              = "Network K Function"
    self.description        = "Uses a Network K Function to analyze clustering and dispersion trends in a set of crash points."
    self.canRunInBackground = False
    env.overwriteOutput     = True

    self.confidenceEnvelopes = OrderedDict([
      ("0 Permutations (No Confidence Envelope)", 0),
      ("9 Permutations", 9),
      ("99 Permutations", 99),
      ("999 Permutations", 999)])
  
  ###
  # Get input from the users.
  ###
  def getParameterInfo(self):
    # First parameter: input origin features.
    points = arcpy.Parameter(
      displayName="Input Points Feature Dataset",
      name="points",
      datatype="Feature Class",
      parameterType="Required",
      direction="Input")
    points.filter.list = ["Point"]

    # Second parameter: network dataset.
    networkDataset = arcpy.Parameter(
      displayName="Input Network Dataset",
      name = "network_dataset",
      datatype="Network Dataset Layer",
      parameterType="Required",
      direction="Input")

    # Third parameter: number of distance increments.
    numBands = arcpy.Parameter(
      displayName="Input Number of Distance Bands",
      name="num_dist_bands",
      datatype="Long",
      parameterType="Optional",
      direction="Input")

    # Fourth parameter: beginning distance.
    begDist = arcpy.Parameter(
      displayName="Input Beginning Distance",
      name="beginning_distance",
      datatype="Double",
      parameterType="Required",
      direction="Input")
    begDist.value = 0

    # Fifth parameter: distance increment.
    distInc = arcpy.Parameter(
      displayName="Input Distance Increment",
      name="distance_increment",
      datatype="Double",
      parameterType="Required",
      direction="Input")
    distInc.value = 1000

    # Sixth parameter: snap distance.
    snapDist = arcpy.Parameter(
      displayName="Input Snap Distance",
      name="snap_distance",
      datatype="Double",
      parameterType="Required",
      direction="Input")
    snapDist.value = 25

    # Seventh parameter: output location.
    outNetKLoc = arcpy.Parameter(
      displayName="Path to Output Network-K Feature Class",
      name="out_location",
      datatype="DEWorkspace",
      parameterType="Required",
      direction="Input")
    outNetKLoc.value = arcpy.env.workspace

    # Eigth parameter: the random point feature class to create.
    outNetKFCName = arcpy.Parameter(
      displayName="Output Network-K Feature Class Name",
      name = "output_point_feature_class",
      datatype="GPString",
      parameterType="Required",
      direction="Output")

    # Ninth parameter: confidence envelope (number of permutations).
    confidenceEnv = arcpy.Parameter(
      displayName="Compute Confidence Envelope",
      name = "confidence_envelope",
      datatype="GPString",
      parameterType="Required",
      direction="Input")
    confKeys                  = self.confidenceEnvelopes.keys();
    confidenceEnv.filter.list = confKeys
    confidenceEnv.value       = confKeys[0]

    # Tenth parameter: projected coordinate system.
    outCoordSys = arcpy.Parameter(
      displayName="Output Network Dataset Length Projected Coordinate System",
      name="coordinate_system",
      datatype="GPSpatialReference",
      parameterType="Optional",
      direction="Input")
   
    return [points, networkDataset, numBands, begDist, distInc, snapDist,
      outNetKLoc, outNetKFCName, confidenceEnv, outCoordSys]

  ###
  # Check if the tool is available for use.
  ###
  def isLicensed(self):
    # Network Analyst tools must be available.
    return arcpy.CheckExtension("Network") == "Available"

  ###
  # Set parameter defaults.
  ###
  def updateParameters(self, parameters):
    networkDataset = parameters[1].value
    outCoordSys    = parameters[9].value

    # Default the coordinate system.
    if networkDataset is not None and outCoordSys is None:
      ndDesc = arcpy.Describe(networkDataset)
      # If the network dataset's coordinate system is a projected one,
      # use its coordinate system as the defualt.
      if (ndDesc.spatialReference.projectionName != "" and
        ndDesc.spatialReference.linearUnitName == "Meter" and
        ndDesc.spatialReference.factoryCode != 0):
        parameters[9].value = ndDesc.spatialReference.factoryCode

    return

  ###
  # If any fields are invalid, show an appropriate error message.
  ###
  def updateMessages(self, parameters):
    outCoordSys = parameters[9].value

    if outCoordSys is not None:
      if outCoordSys.projectionName == "":
        parameters[9].setErrorMessage("Output coordinate system must be a projected coordinate system.")
      elif outCoordSys.linearUnitName != "Meter":
        parameters[9].setErrorMessage("Output coordinate system must have a linear unit code of 'Meter.'")
      else:
        parameters[9].clearMessage()
    return

  ###
  # Execute the tool.
  ###
  def execute(self, parameters, messages):
    points         = parameters[0].valueAsText
    networkDataset = parameters[1].valueAsText
    numBands       = parameters[2].value
    begDist        = parameters[3].value
    distInc        = parameters[4].value
    snapDist       = parameters[5].value
    outNetKLoc     = parameters[6].valueAsText
    outNetKFCName  = parameters[7].valueAsText
    confEnvName    = parameters[8].valueAsText
    confEnvNum     = self.confidenceEnvelopes[confEnvName]
    outCoordSys    = parameters[9].value
    pointsDesc     = arcpy.Describe(points)
    ndDesc         = arcpy.Describe(networkDataset)

    # Refer to the note in the NetworkDatasetLength tool.
    if outCoordSys is None:
      outCoordSys = ndDesc.spatialReference

    messages.addMessage("Origin points: {0}".format(points))
    messages.addMessage("Network dataset: {0}".format(networkDataset))
    messages.addMessage("Number of distance bands: {0}".format(numBands))
    messages.addMessage("Beginning distance: {0}".format(begDist))
    messages.addMessage("Distance increment: {0}".format(distInc))
    messages.addMessage("Snap distance: {0}".format(snapDist))
    messages.addMessage("Path to output network-K feature class: {0}".format(outNetKLoc))
    messages.addMessage("Output network-K feature class name: {0}".format(outNetKFCName))
    messages.addMessage("Compute confidence envelope name: {0} number: {1}".format(confEnvName, confEnvNum))
    messages.addMessage("Network dataset length projected coordinate system: {0}".format(outCoordSys.name))

    # Make the ODCM and calculate the distance between each set of points.
    odcmDistCalc = ODCMDistanceCalculation()
    odDists      = odcmDistCalc.calculateDistances(networkDataset, points, snapDist)
    messages.addMessage("ODCM Distances: {0}".format(odDists))

    # Calculate the length of the network.
    netLenCalc    = NetworkLengthCalculation()
    networkLength = netLenCalc.calculateLength(networkDataset, outCoordSys)
    messages.addMessage("Total network length: {0}".format(networkLength))

    # Do the actual network k-function calculation.
    netKCalc = NetworkKCalculation(networkLength, odDists, begDist, distInc, numBands)
    messages.addMessage("Distance bands: {0}".format(netKCalc.getDistanceBands()))

    # Write the distance bands to a table.
    outNetKFCFullPath = os.path.join(outNetKLoc, outNetKFCName)
    arcpy.CreateTable_management(outNetKLoc, outNetKFCName)

    arcpy.AddField_management(outNetKFCFullPath, "Distance_Band", "DOUBLE")
    arcpy.AddField_management(outNetKFCFullPath, "Point_Count",   "DOUBLE")
    arcpy.AddField_management(outNetKFCFullPath, "K_Function",    "DOUBLE")

    with arcpy.da.InsertCursor(outNetKFCFullPath, ["Distance_Band", "Point_Count", "K_Function"]) as cursor:
      for distBand in netKCalc.getDistanceBands():
        cursor.insertRow([distBand["distanceBand"], distBand["count"], distBand["KFunction"]])
